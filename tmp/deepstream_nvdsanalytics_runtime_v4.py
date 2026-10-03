#!/usr/bin/env python3

################################################################################
# SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
################################################################################

import sys
import os
import re
import math
import signal
import threading
import configparser

sys.path.append('../')

import gi
gi.require_version('Gst', '1.0')
from gi.repository import GLib, Gst

from ctypes import *
from common.platform_info import PlatformInfo
from common.FPS import PERF_DATA
import pyds


# -----------------------------------------------------------------------------
# Camera definitions
# -----------------------------------------------------------------------------
# These are the camera names/config files visible in the user's project.
# The RTSP host/path follows the RTSP URLs explicitly shown by the user:
#   rtsp://65.1.214.31:8554/gj/cam2
#   rtsp://65.1.214.31:8554/gj/cam4
# No run_cam*.sh file is read or parsed by this program.
CAMERAS = {
    # "cam2":  {"slot": 0, "uri": "rtsp://65.1.214.31:8554/gj/cam2",  "analytics": "config_nvdsanalytics_cam2.txt"},
    # "cam4":  {"slot": 1, "uri": "rtsp://65.1.214.31:8554/gj/cam4",  "analytics": "config_nvdsanalytics_cam4.txt"},
    "cam5":  {"slot": 2, "uri": "rtsp://65.1.214.31:8554/gj/cam5",  "analytics": "config_nvdsanalytics_cam5.txt"},
    # "cam5b": {"slot": 3, "uri": "rtsp://65.1.214.31:8554/gj/cam5b", "analytics": "config_nvdsanalytics_cam5b.txt"},
    "cam6":  {"slot": 4, "uri": "rtsp://65.1.214.31:8554/gj/cam6",  "analytics": "config_nvdsanalytics_cam6.txt"},
    "cam12": {"slot": 5, "uri": "rtsp://65.1.214.31:8554/gj/cam12", "analytics": "config_nvdsanalytics_cam12.txt"},
    "cam13": {"slot": 6, "uri": "rtsp://65.1.214.31:8554/gj/cam13", "analytics": "config_nvdsanalytics_cam13.txt"},
    "cam16": {"slot": 7, "uri": "rtsp://65.1.214.31:8554/gj/cam16", "analytics": "config_nvdsanalytics_cam16.txt"},
    "cam20": {"slot": 8, "uri": "rtsp://65.1.214.31:8554/gj/cam20", "analytics": "config_nvdsanalytics_cam20.txt"},
}

MAX_NUM_SOURCES = max(cam["slot"] for cam in CAMERAS.values()) + 1

# -----------------------------------------------------------------------------
# DeepStream constants
# -----------------------------------------------------------------------------
GPU_ID = 0
PGIE_CLASS_ID_PERSON = 0
PGIE_CLASS_ID_BAG = 1
PGIE_CLASS_ID_FACE = 2

MUXER_OUTPUT_WIDTH = 1920
MUXER_OUTPUT_HEIGHT = 1080
MUXER_BATCH_TIMEOUT_USEC = 33000
TILED_OUTPUT_WIDTH = 1280
TILED_OUTPUT_HEIGHT = 720

PGIE_CONFIG_FILE = "dsnvanalytics_pgie_config.txt"
TRACKER_CONFIG_FILE = "dsnvanalytics_tracker_config.txt"
ANALYTICS_RUNTIME_CONFIG = "config_nvdsanalytics_runtime.txt"

OSD_PROCESS_MODE = 0
OSD_DISPLAY_TEXT = 1
pgie_classes_str = ["Person", "Bag", "Face"]


# -----------------------------------------------------------------------------
# Runtime state
# -----------------------------------------------------------------------------
platform_info = None
perf_data = None
loop = None
pipeline = None
streammux = None
pgie = None
tracker = None
nvanalytics = None
tilER = None
nvvidconv = None
nvosd = None
sink = None

source_bin_list = [None] * MAX_NUM_SOURCES
source_enabled = [False] * MAX_NUM_SOURCES
source_name_by_slot = [None] * MAX_NUM_SOURCES
source_eos = [False] * MAX_NUM_SOURCES

state_lock = threading.Lock()


# -----------------------------------------------------------------------------
# Analytics configuration builder
# -----------------------------------------------------------------------------
def build_runtime_analytics_config():
    """Merge every camera's analytics config into one stream-indexed config."""
    base_property = None

    for cam_name, cam in CAMERAS.items():
        path = cam["analytics"]
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"Missing analytics config for {cam_name}: {path}"
            )

    output = []

    # Use the [property] block from the first camera config exactly as supplied.
    first_path = next(iter(CAMERAS.values()))["analytics"]
    first_lines = open(first_path, "r", encoding="utf-8").read().splitlines()

    in_property = False
    for line in first_lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_property = (stripped.lower() == "[property]")
            if not in_property:
                break
            output.append(line)
            continue
        if in_property:
            output.append(line)

    output.append("")

    # Add every camera's stream-specific blocks. stream-0 in each source file
    # becomes stream-<fixed slot>, preserving camera -> stream ID permanently.
    for cam_name, cam in sorted(CAMERAS.items(), key=lambda item: item[1]["slot"]):
        slot = cam["slot"]
        path = cam["analytics"]
        lines = open(path, "r", encoding="utf-8").read().splitlines()

        current_section = None
        wrote_section = False
        for line in lines:
            stripped = line.strip()

            if stripped.startswith("[") and stripped.endswith("]"):
                current_section = stripped[1:-1]
                if current_section.lower() == "property":
                    # Already written once above.
                    current_section = None
                    wrote_section = False
                    continue

                renamed = re.sub(
                    r"-stream-0$",
                    f"-stream-{slot}",
                    current_section,
                    flags=re.IGNORECASE,
                )
                output.append(f"[{renamed}]")
                output.append(f"# camera={cam_name}, stream={slot}")
                wrote_section = True
                continue

            if current_section is None or not wrote_section:
                continue

            output.append(line)

        output.append("")

    with open(ANALYTICS_RUNTIME_CONFIG, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
        f.write("\n")

    print(f"Generated {ANALYTICS_RUNTIME_CONFIG}")
    for cam_name, cam in sorted(CAMERAS.items(), key=lambda item: item[1]["slot"]):
        print(f"  stream {cam['slot']}: {cam_name} -> {cam['analytics']}")


# -----------------------------------------------------------------------------
# Metadata probe
# -----------------------------------------------------------------------------
def nvanalytics_src_pad_buffer_probe(pad, info, u_data):
    gst_buffer = info.get_buffer()
    if not gst_buffer:
        print("Unable to get GstBuffer")
        return Gst.PadProbeReturn.OK

    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    l_frame = batch_meta.frame_meta_list

    while l_frame:
        try:
            frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
        except StopIteration:
            break

        frame_number = frame_meta.frame_num
        stream_id = frame_meta.pad_index
        camera_name = (
            source_name_by_slot[stream_id]
            if 0 <= stream_id < MAX_NUM_SOURCES
            else f"stream{stream_id}"
        )

        l_obj = frame_meta.obj_meta_list
        num_rects = frame_meta.num_obj_meta
        obj_counter = {
            PGIE_CLASS_ID_PERSON: 0,
            PGIE_CLASS_ID_FACE: 0,
            PGIE_CLASS_ID_BAG: 0,
        }

        while l_obj:
            try:
                obj_meta = pyds.NvDsObjectMeta.cast(l_obj.data)
            except StopIteration:
                break

            if obj_meta.class_id in obj_counter:
                obj_counter[obj_meta.class_id] += 1

            l_user_meta = obj_meta.obj_user_meta_list
            while l_user_meta:
                try:
                    user_meta = pyds.NvDsUserMeta.cast(l_user_meta.data)
                    if user_meta.base_meta.meta_type == pyds.nvds_get_user_meta_type(
                        "NVIDIA.DSANALYTICSOBJ.USER_META"
                    ):
                        user_meta_data = pyds.NvDsAnalyticsObjInfo.cast(
                            user_meta.user_meta_data
                        )
                        if user_meta_data.dirStatus:
                            print(
                                f"[{camera_name}] Object {obj_meta.object_id} "
                                f"direction: {user_meta_data.dirStatus}"
                            )
                        if user_meta_data.lcStatus:
                            print(
                                f"[{camera_name}] Object {obj_meta.object_id} "
                                f"line crossing: {user_meta_data.lcStatus}"
                            )
                        if user_meta_data.ocStatus:
                            print(
                                f"[{camera_name}] Object {obj_meta.object_id} "
                                f"overcrowding: {user_meta_data.ocStatus}"
                            )
                        if user_meta_data.roiStatus:
                            print(
                                f"[{camera_name}] Object {obj_meta.object_id} "
                                f"ROI: {user_meta_data.roiStatus}"
                            )
                except StopIteration:
                    break

                try:
                    l_user_meta = l_user_meta.next
                except StopIteration:
                    break

            try:
                l_obj = l_obj.next
            except StopIteration:
                break

        # Frame-level analytics metadata.
        l_user = frame_meta.frame_user_meta_list
        while l_user:
            try:
                user_meta = pyds.NvDsUserMeta.cast(l_user.data)
                if user_meta.base_meta.meta_type == pyds.nvds_get_user_meta_type(
                    "NVIDIA.DSANALYTICSFRAME.USER_META"
                ):
                    user_meta_data = pyds.NvDsAnalyticsFrameMeta.cast(
                        user_meta.user_meta_data
                    )
                    if user_meta_data.objInROIcnt:
                        print(
                            f"[{camera_name}] ROI count: "
                            f"{user_meta_data.objInROIcnt}"
                        )
                    if user_meta_data.objLCCumCnt:
                        print(
                            f"[{camera_name}] line cumulative: "
                            f"{user_meta_data.objLCCumCnt}"
                        )
                    if user_meta_data.objLCCurrCnt:
                        print(
                            f"[{camera_name}] line current: "
                            f"{user_meta_data.objLCCurrCnt}"
                        )
                    if user_meta_data.ocStatus:
                        print(
                            f"[{camera_name}] overcrowding: "
                            f"{user_meta_data.ocStatus}"
                        )
            except StopIteration:
                break

            try:
                l_user = l_user.next
            except StopIteration:
                break

        print(
            f"[{camera_name}] frame={frame_number} stream={stream_id} "
            f"objects={num_rects} person={obj_counter[PGIE_CLASS_ID_PERSON]} "
            f"face={obj_counter[PGIE_CLASS_ID_FACE]}"
        )

        stream_index = f"stream{stream_id}"
        if perf_data is not None:
            perf_data.update_fps(stream_index)

        try:
            l_frame = l_frame.next
        except StopIteration:
            break

    return Gst.PadProbeReturn.OK


# -----------------------------------------------------------------------------
# RTSP decode source
# -----------------------------------------------------------------------------
def decodebin_child_added(child_proxy, obj, name, user_data):
    print(f"Decodebin child added: {name}")
    if "decodebin" in name:
        try:
            obj.connect("child-added", decodebin_child_added, user_data)
        except Exception:
            pass

    if "nvv4l2decoder" in name:
        try:
            if platform_info.is_integrated_gpu():
                obj.set_property("drop-frame-interval", 0)
                obj.set_property("num-extra-surfaces", 0)
            else:
                obj.set_property("enable-max-performance", True)
                obj.set_property("gpu_id", GPU_ID)
        except Exception as e:
            print(f"Decoder property setup warning: {e}")


def cb_newpad(decodebin, decoder_src_pad, source_id):
    print(f"New decoder pad for stream {source_id}")
    caps = decoder_src_pad.get_current_caps()
    if caps is None:
        caps = decoder_src_pad.query_caps(None)
    if caps is None or caps.get_size() == 0:
        print(f"No caps for stream {source_id}")
        return

    gststruct = caps.get_structure(0)
    gstname = gststruct.get_name()
    print(f"gstname={gstname}")

    if "video" not in gstname:
        return

    pad_name = f"sink_{source_id}"
    sinkpad = streammux.request_pad_simple(pad_name)
    if not sinkpad:
        print(f"Unable to request {pad_name}")
        return

    result = decoder_src_pad.link(sinkpad)
    if result == Gst.PadLinkReturn.OK:
        print(f"Stream {source_id} linked to nvstreammux ({pad_name})")
    else:
        print(f"Failed to link stream {source_id}: {result}")
        streammux.release_request_pad(sinkpad)


def create_source_bin(source_id, uri):
    bin_name = f"source-bin-{source_id:02d}"
    print(f"Creating {bin_name}: {uri}")

    source_bin = Gst.Bin.new(bin_name)
    if not source_bin:
        raise RuntimeError(f"Unable to create {bin_name}")

    uri_decode_bin = Gst.ElementFactory.make(
        "uridecodebin", f"uri-decode-bin-{source_id:02d}"
    )
    if not uri_decode_bin:
        raise RuntimeError("Unable to create uridecodebin")

    uri_decode_bin.set_property("uri", uri)
    uri_decode_bin.connect("pad-added", cb_newpad, source_id)
    uri_decode_bin.connect("child-added", decodebin_child_added, source_id)

    source_bin.add(uri_decode_bin)
    return source_bin


# -----------------------------------------------------------------------------
# Tiler
# -----------------------------------------------------------------------------
def update_tiler_layout():
    """Keep a sensible grid while preserving fixed stream IDs."""
    active = sum(source_enabled)
    if active <= 0:
        return

    rows = int(math.sqrt(active))
    rows = max(rows, 1)
    columns = int(math.ceil(active / rows))

    # For nine cameras this is 3x3. For fewer active cameras it shrinks.
    tilER.set_property("rows", rows)
    tilER.set_property("columns", columns)
    tilER.set_property("width", TILED_OUTPUT_WIDTH)
    tilER.set_property("height", TILED_OUTPUT_HEIGHT)

    print(f"Tiler layout: {rows} rows x {columns} columns ({active} active cameras)")


# -----------------------------------------------------------------------------
# Runtime source add/delete
# -----------------------------------------------------------------------------
def add_camera(camera_name):
    camera_name = camera_name.lower()
    if camera_name not in CAMERAS:
        print(
            "Unknown camera. Available: "
            + ", ".join(CAMERAS.keys())
        )
        return False

    cam = CAMERAS[camera_name]
    slot = cam["slot"]

    with state_lock:
        if source_enabled[slot]:
            print(f"{camera_name} is already running on stream {slot}")
            return False
        source_enabled[slot] = True
        source_name_by_slot[slot] = camera_name
        source_eos[slot] = False

    try:
        source_bin = create_source_bin(slot, cam["uri"])
        source_bin_list[slot] = source_bin
        pipeline.add(source_bin)

        ret = source_bin.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError(f"Failed to start source {camera_name}")

        update_tiler_layout()
        print(f"ADDED {camera_name}: stream={slot}, uri={cam['uri']}")
        return True
    except Exception as e:
        with state_lock:
            source_enabled[slot] = False
            source_name_by_slot[slot] = None
            source_eos[slot] = False
        source_bin_list[slot] = None
        print(f"ERROR adding {camera_name}: {e}")
        return False


def remove_camera(camera_name):
    camera_name = camera_name.lower()
    if camera_name not in CAMERAS:
        print(
            "Unknown camera. Available: "
            + ", ".join(CAMERAS.keys())
        )
        return False

    slot = CAMERAS[camera_name]["slot"]

    with state_lock:
        if not source_enabled[slot] or source_bin_list[slot] is None:
            print(f"{camera_name} is not running")
            return False
        source_enabled[slot] = False
        source_eos[slot] = False

    source_bin = source_bin_list[slot]
    print(f"Removing {camera_name} from stream {slot}")

    try:
        source_bin.set_state(Gst.State.NULL)

        pad_name = f"sink_{slot}"
        sinkpad = streammux.get_static_pad(pad_name)
        if sinkpad:
            try:
                sinkpad.send_event(Gst.Event.new_flush_stop(False))
            except Exception:
                pass
            streammux.release_request_pad(sinkpad)

        pipeline.remove(source_bin)
        source_bin_list[slot] = None
        source_name_by_slot[slot] = None
        source_eos[slot] = False

        update_tiler_layout()
        print(f"REMOVED {camera_name} (stream {slot})")
        return True
    except Exception as e:
        print(f"ERROR removing {camera_name}: {e}")
        source_bin_list[slot] = None
        source_name_by_slot[slot] = None
        source_eos[slot] = False
        return False


def add_camera_initial(camera_name):
    """Add the first source before the pipeline state transition."""
    camera_name = camera_name.lower()
    if camera_name not in CAMERAS:
        print(f"Unknown initial camera: {camera_name}")
        return False

    cam = CAMERAS[camera_name]
    slot = cam["slot"]

    if source_enabled[slot] or source_bin_list[slot] is not None:
        return True

    source_bin = create_source_bin(slot, cam["uri"])
    pipeline.add(source_bin)
    source_bin_list[slot] = source_bin
    source_enabled[slot] = True
    source_name_by_slot[slot] = camera_name
    source_eos[slot] = False
    print(f"INITIAL SOURCE: {camera_name} -> stream {slot} -> {cam['uri']}")
    return True


def add_all_cameras_except(excluded_camera):
    """Add all configured cameras except the already-running initial source."""
    delay = 2
    for camera_name in CAMERAS.keys():
        if camera_name == excluded_camera:
            continue
        GLib.timeout_add_seconds(
            delay,
            lambda name=camera_name: (add_camera(name), False)[1],
        )
        delay += 2


# -----------------------------------------------------------------------------
# Command interface
# -----------------------------------------------------------------------------
def print_status():
    print("\nCamera status:")
    for cam_name, cam in sorted(CAMERAS.items(), key=lambda item: item[1]["slot"]):
        slot = cam["slot"]
        status = "RUNNING" if source_enabled[slot] else "STOPPED"
        print(f"  stream {slot}: {cam_name:<5} {status}")
    print()


def handle_command(command):
    command = command.strip()
    if not command:
        return False

    parts = command.split()
    op = parts[0].lower()

    if op in ("quit", "exit", "q"):
        print("Stopping pipeline...")
        loop.quit()
        return False

    if op in ("status", "list"):
        print_status()
        return False

    if op == "add" and len(parts) == 2:
        add_camera(parts[1])
        return False

    if op in ("del", "remove", "rm") and len(parts) == 2:
        remove_camera(parts[1])
        return False

    if op == "all":
        for name in CAMERAS:
            if not source_enabled[CAMERAS[name]["slot"]]:
                add_camera(name)
        return False

    if op == "help":
        print(
            "Commands:\n"
            "  status              show camera status\n"
            "  add camX            add a camera\n"
            "  del camX            remove a camera\n"
            "  all                 add all cameras\n"
            "  quit                stop the application"
        )
        return False

    print("Invalid command. Type 'help'.")
    return False


def stdin_worker():
    print(
        "\nRuntime controls:\n"
        "  status\n"
        "  add cam2\n"
        "  del cam2\n"
        "  all\n"
        "  quit\n"
    )
    while True:
        try:
            command = input("camera> ")
        except EOFError:
            GLib.idle_add(lambda: (loop.quit(), False)[1])
            return
        except Exception:
            return

        GLib.idle_add(handle_command, command)
        if command.strip().lower() in ("quit", "exit", "q"):
            return


# -----------------------------------------------------------------------------
# Bus callback
# -----------------------------------------------------------------------------
def bus_call(bus, message, main_loop):
    message_type = message.type

    if message_type == Gst.MessageType.EOS:
        print("Pipeline EOS")
        main_loop.quit()

    elif message_type == Gst.MessageType.WARNING:
        err, debug = message.parse_warning()
        print(f"WARNING: {err}: {debug}")

    elif message_type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        src_name = message.src.get_name() if message.src else "unknown"
        print(f"ERROR from {src_name}: {err}")
        if debug:
            print(f"DEBUG: {debug}")

        # Keep the multi-camera app alive when an individual source fails.
        # Runtime add/delete can then be used to restart that camera.
        if src_name.startswith("source-bin-") or "uri-decode-bin-" in src_name:
            return True

        main_loop.quit()

    elif message_type == Gst.MessageType.ELEMENT:
        structure = message.get_structure()
        if structure is not None and structure.has_name("stream-eos"):
            parsed, stream_id = structure.get_uint("stream-id")
            if parsed and 0 <= stream_id < MAX_NUM_SOURCES:
                source_eos[stream_id] = True
                cam = source_name_by_slot[stream_id]
                print(f"EOS from stream {stream_id} ({cam})")

    return True


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    global platform_info
    global perf_data
    global loop
    global pipeline
    global streammux
    global pgie
    global tracker
    global nvanalytics
    global tilER
    global nvvidconv
    global nvosd
    global sink

    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    platform_info = PlatformInfo()
    Gst.init(None)

    print("=" * 80)
    print("DeepStream PeopleNet + NvDCF + NvDsAnalytics Runtime Source Manager")
    print("=" * 80)

    build_runtime_analytics_config()

    pipeline = Gst.Pipeline.new("deepstream-pipeline")
    if not pipeline:
        raise RuntimeError("Unable to create pipeline")

    streammux = Gst.ElementFactory.make("nvstreammux", "Stream-muxer")
    pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
    tracker = Gst.ElementFactory.make("nvtracker", "tracker")
    nvanalytics = Gst.ElementFactory.make("nvdsanalytics", "analytics")
    tilER = Gst.ElementFactory.make("nvmultistreamtiler", "nvtiler")
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "convertor")
    nvosd = Gst.ElementFactory.make("nvdsosd", "onscreendisplay")

    if platform_info.is_integrated_gpu():
        sink = Gst.ElementFactory.make("nv3dsink", "nv3d-sink")
    elif platform_info.is_platform_aarch64():
        sink = Gst.ElementFactory.make("nv3dsink", "nv3d-sink")
    else:
        sink = Gst.ElementFactory.make("nveglglessink", "nvvideo-renderer")

    elements = [streammux, pgie, tracker, nvanalytics, tilER, nvvidconv, nvosd, sink]
    names = [
        "nvstreammux",
        "nvinfer",
        "nvtracker",
        "nvdsanalytics",
        "nvmultistreamtiler",
        "nvvideoconvert",
        "nvdsosd",
        "sink",
    ]
    for name, element in zip(names, elements):
        if not element:
            raise RuntimeError(f"Unable to create {name}")

    # nvstreammux is sized for the maximum number of runtime slots.
    streammux.set_property("width", MUXER_OUTPUT_WIDTH)
    streammux.set_property("height", MUXER_OUTPUT_HEIGHT)
    streammux.set_property("batch-size", MAX_NUM_SOURCES)
    streammux.set_property("batched-push-timeout", MUXER_BATCH_TIMEOUT_USEC)
    streammux.set_property("live-source", 1)
    streammux.set_property("gpu_id", GPU_ID)

    # Keep PGIE batch-size exactly as configured in dsnvanalytics_pgie_config.txt.
    # The current configuration is batch-size=1, so inference remains B1 even
    # though nvstreammux holds up to MAX_NUM_SOURCES frames in its batch.
    pgie.set_property("config-file-path", PGIE_CONFIG_FILE)
    pgie.set_property("gpu_id", GPU_ID)
    configured_batch = pgie.get_property("batch-size")
    print(f"PGIE batch-size: {configured_batch} (kept as configured)")
    if configured_batch != 1:
        raise RuntimeError(
            f"Expected PGIE batch-size=1, but dsnvanalytics_pgie_config.txt "
            f"sets batch-size={configured_batch}"
        )

    # Tracker config from the user's existing file.
    tracker_config = configparser.ConfigParser()
    tracker_config.read(TRACKER_CONFIG_FILE)
    if "tracker" not in tracker_config:
        raise RuntimeError(f"Missing [tracker] section in {TRACKER_CONFIG_FILE}")

    for key, value in tracker_config["tracker"].items():
        if key == "tracker-width":
            tracker.set_property("tracker-width", tracker_config.getint("tracker", key))
        elif key == "tracker-height":
            tracker.set_property("tracker-height", tracker_config.getint("tracker", key))
        elif key == "gpu-id":
            tracker.set_property("gpu_id", tracker_config.getint("tracker", key))
        elif key == "ll-lib-file":
            tracker.set_property("ll-lib-file", value)
        elif key == "ll-config-file":
            tracker.set_property("ll-config-file", value)
        elif key == "enable-batch-process":
            tracker.set_property(
                "enable_batch_process",
                tracker_config.getint("tracker", key),
            )

    nvanalytics.set_property("config-file", ANALYTICS_RUNTIME_CONFIG)

    tilER.set_property("rows", 3)
    tilER.set_property("columns", 3)
    tilER.set_property("width", TILED_OUTPUT_WIDTH)
    tilER.set_property("height", TILED_OUTPUT_HEIGHT)
    tilER.set_property("gpu_id", GPU_ID)

    nvvidconv.set_property("gpu_id", GPU_ID)
    nvosd.set_property("process-mode", OSD_PROCESS_MODE)
    nvosd.set_property("display-text", OSD_DISPLAY_TEXT)
    nvosd.set_property("gpu_id", GPU_ID)

    sink.set_property("qos", 0)
    try:
        sink.set_property("sync", 0)
    except Exception:
        pass
    if not platform_info.is_integrated_gpu() and not platform_info.is_platform_aarch64():
        try:
            sink.set_property("gpu_id", GPU_ID)
        except Exception:
            pass

    for element in elements:
        pipeline.add(element)

    # Main pipeline. One initial source is inserted before the first state
    # transition; remaining sources are inserted at runtime.
    if not streammux.link(pgie):
        raise RuntimeError("Failed to link nvstreammux -> nvinfer")
    if not pgie.link(tracker):
        raise RuntimeError("Failed to link nvinfer -> nvtracker")
    if not tracker.link(nvanalytics):
        raise RuntimeError("Failed to link nvtracker -> nvdsanalytics")
    if not nvanalytics.link(tilER):
        raise RuntimeError("Failed to link nvdsanalytics -> tiler")
    if not tilER.link(nvvidconv):
        raise RuntimeError("Failed to link tiler -> nvvideoconvert")
    if not nvvidconv.link(nvosd):
        raise RuntimeError("Failed to link nvvideoconvert -> nvdsosd")
    if not nvosd.link(sink):
        raise RuntimeError("Failed to link nvdsosd -> sink")

    # Analytics metadata probe.
    analytics_src_pad = nvanalytics.get_static_pad("src")
    if not analytics_src_pad:
        raise RuntimeError("Unable to get nvdsanalytics src pad")
    analytics_src_pad.add_probe(
        Gst.PadProbeType.BUFFER,
        nvanalytics_src_pad_buffer_probe,
        None,
    )

    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, loop)

    perf_data = PERF_DATA(MAX_NUM_SOURCES)
    GLib.timeout_add(5000, perf_data.perf_print_callback)

    # Graceful Ctrl-C.
    def sigint_handler(signum, frame):
        if loop is not None:
            loop.quit()

    signal.signal(signal.SIGINT, sigint_handler)
    signal.signal(signal.SIGTERM, sigint_handler)

    # NVIDIA\'s runtime-source sample brings the pipeline up with a source
    # already present, then adds/removes additional sources at runtime.
    # Do the same here. Starting a DeepStream pipeline with zero source pads
    # can cause native plugins to abort during state change on some builds.
    # Keep one source in the pipeline before the initial state transition,
    # matching NVIDIA's runtime-source sample. Do not wait for an exact
    # PLAYING state here: RTSP negotiation is asynchronous and a live
    # uridecodebin can legitimately remain pending while it connects.
    initial_camera = "cam2"
    print(f"\nAdding initial camera {initial_camera} before pipeline state change...")
    if not add_camera_initial(initial_camera):
        raise RuntimeError(f"Failed to add initial camera {initial_camera}")

    print("\nStarting pipeline...")
    pipeline.set_state(Gst.State.PAUSED)
    print("Pipeline PAUSED state transition requested")

    pipeline.set_state(Gst.State.PLAYING)
    print("Pipeline PLAYING state transition requested; RTSP negotiation will continue asynchronously")

    # Read commands without blocking the GLib main loop.
    command_thread = threading.Thread(target=stdin_worker, daemon=True)
    command_thread.start()

    # Add the remaining cameras through the runtime source mechanism.
    add_all_cameras_except("cam2")

    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping all runtime sources...")
        for cam_name, cam in sorted(CAMERAS.items(), key=lambda item: item[1]["slot"]):
            slot = cam["slot"]
            if source_bin_list[slot] is not None:
                try:
                    remove_camera(cam_name)
                except Exception as e:
                    print(f"Cleanup error for {cam_name}: {e}")

        pipeline.set_state(Gst.State.NULL)
        print("Pipeline stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
