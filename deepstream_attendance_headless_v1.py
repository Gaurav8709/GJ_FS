#!/usr/bin/env python3

import sys
sys.path.append('../')
import gi
import configparser

gi.require_version('Gst', '1.0')
from gi.repository import GLib, Gst
from ctypes import *
import time
import math
import platform
import numpy as np
import pyds
import cv2
import os
import shutil
from datetime import datetime

# DeepStream Common Imports
from common.platform_info import PlatformInfo
from common.bus_call import bus_call
from common.FPS import PERF_DATA

# Pure TensorRT Imports
import tensorrt as trt
import pycuda.driver as cuda

from collections import Counter

MATCH_HISTORY_SIZE = 10
match_history = {}

# ==========================================
# CONFIGURATION
# ==========================================
REGISTERED_DIR = 'registered_users'
ATTENDANCE_ROOT_DIR = 'attendance_records'

DET_ENGINE_PATH = 'models/det_model.engine' 
REC_ENGINE_PATH = 'models/rec_model.engine' 

CONFIDENCE_THRESHOLD = 0.5
REQUIRED_DURATION = 0.0 
presence_tracker = {}

MUXER_OUTPUT_WIDTH = 1920
MUXER_OUTPUT_HEIGHT = 1080
MUXER_BATCH_TIMEOUT_USEC = 33000
TILED_OUTPUT_WIDTH = 1920
TILED_OUTPUT_HEIGHT = 1080

perf_data = None
platform_info = None

if not os.path.exists(REGISTERED_DIR):
    os.makedirs(REGISTERED_DIR)

# ==========================================
# TENSORRT EXECUTION ENGINE WITH CONTEXT COUPLING
# ==========================================

class TRTRunner:
    def __init__(self, engine_path, cuda_context):
        self.logger = trt.Logger(trt.Logger.WARNING)
        trt.init_libnvinfer_plugins(self.logger, '')
        
        self.ctx = cuda_context
        self.ctx.push()
        
        with open(engine_path, "rb") as f, trt.Runtime(self.logger) as runtime:
            self.engine = runtime.deserialize_cuda_engine(f.read())
            
        self.context = self.engine.create_execution_context()
        self.stream = cuda.Stream()
        
        self.inputs = []
        self.outputs = []
        self.allocations = {}
        
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            dtype = trt.nptype(self.engine.get_tensor_dtype(name))
            shape = self.engine.get_tensor_shape(name)
            mode = self.engine.get_tensor_mode(name)
            
            if mode == trt.TensorIOMode.INPUT:
                self.inputs.append({'name': name, 'dtype': dtype, 'shape': shape})
            else:
                self.outputs.append({'name': name, 'dtype': dtype, 'shape': shape})
                
        self.ctx.pop()

    def __call__(self, input_data):
        self.ctx.push()
        
        inp = self.inputs[0]
        name = inp['name']
        self.context.set_input_shape(name, input_data.shape)
        
        for io_tensor in self.inputs + self.outputs:
            t_name = io_tensor['name']
            t_dtype = io_tensor['dtype']
            t_shape = self.context.get_tensor_shape(t_name)
            size = trt.volume(t_shape) * np.dtype(t_dtype).itemsize
            
            if t_name not in self.allocations or self.allocations[t_name]['size'] < size:
                if t_name in self.allocations:
                    self.allocations[t_name]['ptr'].free()
                self.allocations[t_name] = {'ptr': cuda.mem_alloc(size), 'size': size}
            self.context.set_tensor_address(t_name, int(self.allocations[t_name]['ptr']))
            
        input_data = np.ascontiguousarray(input_data, dtype=inp['dtype'])
        cuda.memcpy_htod_async(self.allocations[name]['ptr'], input_data, self.stream)
        self.context.execute_async_v3(stream_handle=self.stream.handle)
        
        results = []
        for out in self.outputs:
            t_name = out['name']
            t_shape = self.context.get_tensor_shape(t_name)
            out_data = np.empty(t_shape, dtype=out['dtype'])
            cuda.memcpy_dtoh_async(out_data, self.allocations[t_name]['ptr'], self.stream)
            results.append(out_data)
            
        self.stream.synchronize()
        self.ctx.pop()
        return results

# ==========================================
# PURE NUMPY PRE/POST PROCESSING 
# ==========================================

class Face:
    def __init__(self, bbox, kps, det_score):
        self.bbox = bbox
        self.kps = kps
        self.det_score = det_score
        self.embedding = None

class PureSCRFD:
    def __init__(self, engine_path, cuda_context, input_size=(640, 640), conf_thresh=0.5, nms_thresh=0.4):
        self.engine = TRTRunner(engine_path, cuda_context)
        self.input_size = input_size
        self.conf_thresh = conf_thresh
        self.nms_thresh = nms_thresh
        self.strides = [8, 16, 32]
        self.center_cache = self._generate_anchors()

    def _generate_anchors(self):
        cache = {}
        for stride in self.strides:
            h, w = self.input_size[0] // stride, self.input_size[1] // stride
            grid_y, grid_x = np.mgrid[0:h, 0:w]
            grid = np.stack((grid_x, grid_y), axis=-1).astype(np.float32)
            grid = (grid * stride) + (stride // 2)
            cache[stride] = np.repeat(grid.reshape(-1, 2), 2, axis=0)
        return cache

    def detect(self, img):
        ratio = min(self.input_size[0] / img.shape[0], self.input_size[1] / img.shape[1])
        new_w, new_h = int(img.shape[1] * ratio), int(img.shape[0] * ratio)
        resized = cv2.resize(img, (new_w, new_h))
        
        pad_img = np.zeros((self.input_size[0], self.input_size[1], 3), dtype=np.uint8)
        pad_img[:new_h, :new_w, :] = resized
        
        pad_img_rgb = pad_img[:, :, ::-1] 
        blob = (pad_img_rgb.astype(np.float32) - 127.5) / 128.0
        blob = np.expand_dims(blob.transpose(2, 0, 1), axis=0)
        
        outputs = self.engine(blob)
        scores, bboxes, kpss = [], [], []
        
        for out in outputs:
            out = out.reshape(-1, out.shape[-1]) 
            num_points = out.shape[0]
            stride = 8 if num_points == 12800 else (16 if num_points == 3200 else 32)
            if out.shape[1] == 1: scores.append((stride, out))
            elif out.shape[1] == 4: bboxes.append((stride, out))
            elif out.shape[1] == 10: kpss.append((stride, out))

        scores, bboxes, kpss = dict(scores), dict(bboxes), dict(kpss)
        final_boxes, final_kps, final_scores = [], [], []
        
        for stride in self.strides:
            score = scores[stride].flatten()
            mask = score > self.conf_thresh
            if not mask.any(): continue
            valid_scores = score[mask]
            valid_centers = self.center_cache[stride][mask]
            
            bbox_reg = bboxes[stride][mask]
            x1 = valid_centers[:, 0] - bbox_reg[:, 0] * stride
            y1 = valid_centers[:, 1] - bbox_reg[:, 1] * stride
            x2 = valid_centers[:, 0] + bbox_reg[:, 2] * stride
            y2 = valid_centers[:, 1] + bbox_reg[:, 3] * stride
            valid_boxes = np.stack([x1, y1, x2, y2], axis=-1) / ratio
            
            kps_reg = kpss[stride][mask]
            valid_kps = []
            for i in range(0, 10, 2):
                kx = valid_centers[:, 0] + kps_reg[:, i] * stride
                ky = valid_centers[:, 1] + kps_reg[:, i+1] * stride
                valid_kps.append(kx)
                valid_kps.append(ky)
            valid_kps = np.stack(valid_kps, axis=-1).reshape(-1, 5, 2) / ratio
            
            final_boxes.extend(valid_boxes)
            final_kps.extend(valid_kps)
            final_scores.extend(valid_scores)
            
        if not final_boxes: return []
        
        final_boxes = np.array(final_boxes)
        final_scores = np.array(final_scores)
        final_kps = np.array(final_kps)
        
        xywh_boxes = final_boxes.copy()
        xywh_boxes[:, 2] = xywh_boxes[:, 2] - xywh_boxes[:, 0]
        xywh_boxes[:, 3] = xywh_boxes[:, 3] - xywh_boxes[:, 1]
        
        indices = cv2.dnn.NMSBoxes(xywh_boxes.tolist(), final_scores.tolist(), self.conf_thresh, self.nms_thresh)
        faces = [Face(final_boxes[i], final_kps[i], final_scores[i]) for i in indices.flatten()]
        return faces

class PureArcFace:
    def __init__(self, engine_path, cuda_context):
        self.engine = TRTRunner(engine_path, cuda_context)
        self.src_pts = np.array([
            [38.2946, 51.6963], [73.5318, 51.5014],
            [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
        ], dtype=np.float32)

    def align(self, img, kps):
        tform = cv2.estimateAffinePartial2D(kps, self.src_pts, method=cv2.LMEDS)[0]
        # UPGRADE 1: Use INTER_CUBIC for high-quality mathematical zooming instead of default linear
        return cv2.warpAffine(img, tform, (112, 112), flags=cv2.INTER_CUBIC)

    def get_feat(self, imgs):
        feats = []
        for img in imgs:
            img_rgb = img[:, :, ::-1]
            blob = (img_rgb.astype(np.float32) / 127.5) - 1.0
            blob = np.expand_dims(blob.transpose(2, 0, 1), axis=0)
            feat = self.engine(blob)[0].flatten()
            feats.append(feat)
        return feats

    def get(self, img, face):
        aligned = self.align(img, face.kps)
        
        # UPGRADE 2: Apply a gentle Unsharp Mask to the zoomed 112x112 image to define edges for the AI
        gaussian = cv2.GaussianBlur(aligned, (0, 0), 2.0)
        sharpened = cv2.addWeighted(aligned, 1.5, gaussian, -0.5, 0)
        
        aligned_rgb = sharpened[:, :, ::-1] # Use the sharpened image
        blob = (aligned_rgb.astype(np.float32) / 127.5) - 1.0
        blob = np.expand_dims(blob.transpose(2, 0, 1), axis=0)
        feat = self.engine(blob)[0].flatten()
        norm = np.linalg.norm(feat)
        face.embedding = feat / norm if norm != 0 else feat

class TensorRTFacePipeline:
    def __init__(self, det_engine, rec_engine, cuda_context):
        self.det_model = PureSCRFD(det_engine, cuda_context)
        self.rec_model = PureArcFace(rec_engine, cuda_context)

    def get(self, img):
        faces = self.det_model.detect(img)
        for face in faces:
            self.rec_model.get(img, face)
        return faces

# ==========================================
# ATTENDANCE & LOGIC FUNCTIONS
# ==========================================

def get_today_paths():
    today_str = datetime.now().strftime('%d-%m-%Y')
    daily_dir = os.path.join(ATTENDANCE_ROOT_DIR, today_str)
    return (os.path.join(daily_dir, 'present'), 
            os.path.join(daily_dir, 'absent'), 
            os.path.join(daily_dir, 'evidence'))

def setup_daily_attendance(known_names):
    present_dir, absent_dir, evidence_dir = get_today_paths()
    os.makedirs(present_dir, exist_ok=True)
    os.makedirs(absent_dir, exist_ok=True)
    os.makedirs(evidence_dir, exist_ok=True)
    for name in set(known_names):
        absent_file = os.path.join(absent_dir, f"{name}.txt")
        if not os.path.exists(os.path.join(present_dir, f"{name}.txt")) and not os.path.exists(absent_file):
            with open(absent_file, 'w') as f: f.write(f"Created: {datetime.now().strftime('%H:%M:%S')}")

def mark_attendance(user_id, frame_capture):
    present_dir, absent_dir, evidence_dir = get_today_paths()
    absent_file = os.path.join(absent_dir, f"{user_id}.txt")
    present_file = os.path.join(present_dir, f"{user_id}.txt")
    timestamp = datetime.now().strftime('%H-%M-%S')
    proof_path = os.path.join(evidence_dir, f"{user_id}_{timestamp}.jpg")

    if os.path.exists(absent_file):
        shutil.move(absent_file, present_file)
        with open(present_file, 'w') as f: f.write(f"Present marked at: {datetime.now().strftime('%H:%M:%S')}")
        cv2.imwrite(proof_path, frame_capture)
        return True
    elif os.path.exists(present_file):
        return False
    else:
        with open(present_file, 'w') as f: f.write(f"Present marked at: {datetime.now().strftime('%H:%M:%S')}")
        cv2.imwrite(proof_path, frame_capture)
        return True

def load_known_faces(ai_pipeline):
    known_embeddings, known_names = [], []
    print(f"Loading users from '{REGISTERED_DIR}'...")
    if not os.path.exists(REGISTERED_DIR): os.makedirs(REGISTERED_DIR)
        
    for entry in os.listdir(REGISTERED_DIR):
        entry_path = os.path.join(REGISTERED_DIR, entry)
        if os.path.isdir(entry_path):
            for filename in os.listdir(entry_path):
                if filename.lower().endswith((".jpg", ".png", ".jpeg", ".bmp", ".pgm")):
                    img = cv2.imread(os.path.join(entry_path, filename))
                    if img is None: continue
                    
                    try:
                        face_img = cv2.resize(img, (112, 112))
                        feat = ai_pipeline.rec_model.get_feat([face_img])
                        if feat and len(feat) > 0:
                            emb = feat[0]
                            norm = np.linalg.norm(emb)
                            known_embeddings.append(emb / norm if norm != 0 else emb)
                            known_names.append(entry)
                    except Exception as e:
                        print(f"Error loading {filename}: {e}")

    print(f"Loaded {len(known_embeddings)} face embeddings for {len(set(known_names))} unique users.")
    return known_embeddings, known_names

# ==========================================
# DEEPSTREAM PIPELINE LOGIC
# ==========================================

global ai_pipeline, feature_bank, known_names
global last_fps_time, frame_fps_counter, current_fps_val

last_fps_time = time.time()
frame_fps_counter = 0
current_fps_val = 0.0

def tiler_sink_pad_buffer_probe(pad, info, u_data):
    global last_fps_time, frame_fps_counter, current_fps_val
    gst_buffer = info.get_buffer()
    if not gst_buffer: return Gst.PadProbeReturn.OK

    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    l_frame = batch_meta.frame_meta_list

    frame_fps_counter += 1
    t_now = time.time()
    if (t_now - last_fps_time) >= 1.0:
        current_fps_val = frame_fps_counter / (t_now - last_fps_time)
        frame_fps_counter = 0
        last_fps_time = t_now

    while l_frame is not None:
        try:
            frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
        except StopIteration:
            break

        n_frame = pyds.get_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)
        frame_copy = np.array(n_frame, copy=True, order='C')
        frame_bgr = cv2.cvtColor(frame_copy, cv2.COLOR_RGBA2BGR)
        
        
        t_ai_start = time.time()
        faces = ai_pipeline.get(frame_bgr)
        
        ai_latency = (time.time() - t_ai_start) * 1000
        
        current_frame_names = set()

        for face in faces:
            
            
            # DEFAULT EXTENSIONS FOR UNKNOWN
            name, text = "Unknown", "Unknown"
            color = (1.0, 0.0, 0.0, 1.0) # Pure Red
            
            if len(feature_bank) > 0:
                sims = np.dot(feature_bank, face.embedding)
                max_idx = np.argmax(sims)
                max_score = sims[max_idx]
                
                # if max_score > CONFIDENCE_THRESHOLD:
                #     name = known_names[max_idx]
                #     current_frame_names.add(name)
                    
                #     if name not in presence_tracker:
                #         presence_tracker[name] = time.time()
                #         text = "Verifying..."
                #         color = (1.0, 1.0, 0.0, 1.0) # Yellow
                #     else:
                #         elapsed = time.time() - presence_tracker[name]
                #         if elapsed >= REQUIRED_DURATION:
                #             mark_attendance(name, frame_bgr)
                #             text = f"{name} ({int(max_score*100)}%)" # Correct matching string structure
                #             color = (0.0, 1.0, 0.0, 1.0) # Pure Green
                #         else:
                #             text = f"{name} {elapsed:.1f}s"

                # Track prediction history per face
                history_key = id(face)

                if history_key not in match_history:
                    match_history[history_key] = []

                if max_score > CONFIDENCE_THRESHOLD:
                    match_history[history_key].append((known_names[max_idx], max_score))
                else:
                    match_history[history_key].append(("Unknown", max_score))

                # Keep only latest 10 frames
                match_history[history_key] = match_history[history_key][-MATCH_HISTORY_SIZE:]

                # ------------------------------------------
                # 10-frame voting logic
                # ------------------------------------------
                if len(match_history[history_key]) >= MATCH_HISTORY_SIZE:
                    votes = [
                        n for n, score in match_history[history_key] if n != "Unknown"
                    ]

                    if votes:
                        voted_name, vote_count = Counter(votes).most_common(1)[0]

                        # Require majority: at least 6/10 frames
                        if vote_count >= 6:
                            name = voted_name
                            current_frame_names.add(name)

                            # Calculate average similarity score for the voted person
                            matching_scores = [
                                score
                                for n, score in match_history[history_key]
                                if n == voted_name
                            ]
                            avg_score = np.mean(matching_scores)

                            if name not in presence_tracker:
                                presence_tracker[name] = time.time()
                                text = "Verifying..."
                                color = (1.0, 1.0, 0.0, 1.0)  # Yellow
                            else:
                                elapsed = time.time() - presence_tracker[name]
                                if elapsed >= REQUIRED_DURATION:
                                    mark_attendance(name, frame_bgr)
                                    text = f"{name} ({int(avg_score * 100)}%)"
                                    color = (0.0, 1.0, 0.0, 1.0)  # Pure Green
                                else:
                                    text = f"{name} {elapsed:.1f}s"
            
            obj_meta = pyds.nvds_acquire_obj_meta_from_pool(batch_meta)
            obj_meta.class_id = 0
            obj_meta.confidence = face.det_score
            
            rect = obj_meta.rect_params
            rect.left, rect.top = float(face.bbox[0]), float(face.bbox[1])
            rect.width = float(face.bbox[2] - face.bbox[0])
            rect.height = float(face.bbox[3] - face.bbox[1])
            rect.border_width = 3
            rect.border_color.set(color[0], color[1], color[2], color[3])
            
            txt = obj_meta.text_params
            txt.display_text = text
            txt.font_params.font_name = "Serif"
            txt.font_params.font_size = 12
            txt.font_params.font_color.set(1.0, 1.0, 1.0, 1.0)
            txt.set_bg_clr = 1
            txt.text_bg_clr.set(0.0, 0.0, 0.0, 1.0)

            # Text coordinates matched to bounding box coordinates as integers
            txt.x_offset = int(rect.left)
            txt.y_offset = max(0, int(rect.top) - 50)
            
            pyds.nvds_add_obj_meta_to_frame(frame_meta, obj_meta, None)

        for tracked in list(presence_tracker.keys()):
            if tracked not in current_frame_names: del presence_tracker[tracked]

        # ---------------------------------------------------------
        # DISPLAY METADATA INJECTION (FIXED FLAT API STRUCTURE)
        # ---------------------------------------------------------
        display_meta = pyds.nvds_acquire_display_meta_from_pool(batch_meta)
        display_meta.num_labels = 2
        
        # Indicator 1: Display FPS Flat Assignment Configuration
        txt_fps = display_meta.text_params[0]
        txt_fps.display_text = f"Display FPS: {int(current_fps_val)}"
        txt_fps.x_offset = 30
        txt_fps.y_offset = 40
        txt_fps.font_params.font_name = "Arial"
        txt_fps.font_params.font_size = 22
        txt_fps.font_params.font_color.set(1.0, 1.0, 0.0, 1.0) # Yellow Text
        txt_fps.set_bg_clr = 0

        # Indicator 2: GPU AI Latency Flat Assignment Configuration
        txt_lat = display_meta.text_params[1]
        txt_lat.display_text = f"GPU AI Latency: {ai_latency:.1f} ms"
        txt_lat.x_offset = 30
        txt_lat.y_offset = 80
        txt_lat.font_params.font_name = "Arial"
        txt_lat.font_params.font_size = 22
        txt_lat.font_params.font_color.set(0.0, 1.0, 0.0, 1.0) # Green Text
        txt_lat.set_bg_clr = 0

        pyds.nvds_add_display_meta_to_frame(frame_meta, display_meta)

        stream_index = "stream{0}".format(frame_meta.pad_index)
        global perf_data
        perf_data.update_fps(stream_index)
        
        if platform_info.is_integrated_gpu():
            pyds.unmap_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)

        try:
            l_frame = l_frame.next
        except StopIteration:
            break

    return Gst.PadProbeReturn.OK

def cb_newpad(decodebin, decoder_src_pad, data):
    caps = decoder_src_pad.get_current_caps()
    if caps.get_structure(0).get_name().find("video") != -1:
        if caps.get_features(0).contains("memory:NVMM"):
            bin_ghost_pad = data.get_static_pad("src")
            bin_ghost_pad.set_target(decoder_src_pad)

def decodebin_child_added(child_proxy, Object, name, user_data):
    if name.find("decodebin") != -1:
        Object.connect("child-added", decodebin_child_added, user_data)
    if not platform_info.is_integrated_gpu() and name.find("nvv4l2decoder") != -1:
        Object.set_property("cudadec-memtype", 2)
    if "source" in name:
        source_element = child_proxy.get_by_name("source")
        if source_element.find_property('drop-on-latency') != None:
            Object.set_property("drop-on-latency", True)

def create_source_bin(index, uri):
    bin_name = "source-bin-%02d" % index
    nbin = Gst.Bin.new(bin_name)
    uri_decode_bin = Gst.ElementFactory.make("uridecodebin", "uri-decode-bin")
    uri_decode_bin.set_property("uri", uri)
    uri_decode_bin.connect("pad-added", cb_newpad, nbin)
    uri_decode_bin.connect("child-added", decodebin_child_added, nbin)
    Gst.Bin.add(nbin, uri_decode_bin)
    nbin.add_pad(Gst.GhostPad.new_no_target("src", Gst.PadDirection.SRC))
    return nbin

def main(args):
    global perf_data, platform_info, ai_pipeline, feature_bank, known_names
    
    if len(args) < 2:
        sys.stderr.write("usage: %s <uri1> [uri2] ... [uriN]\n" % args[0])
        sys.exit(1)

    cuda.init()
    cuda_device = cuda.Device(0)
    cuda_context = cuda_device.make_context()

    print("Initializing Native TensorRT AI Pipeline...")
    ai_pipeline = TensorRTFacePipeline(DET_ENGINE_PATH, REC_ENGINE_PATH, cuda_context)
    
    emb, nms = load_known_faces(ai_pipeline)
    
    cuda_context.push()
    feature_bank = np.array(emb) if emb else np.empty((0, 512))
    cuda_context.pop()
    
    known_names = nms
    setup_daily_attendance(known_names)

    number_sources = len(args) - 1
    perf_data = PERF_DATA(number_sources)
    platform_info = PlatformInfo()
    Gst.init(None)

    pipeline = Gst.Pipeline()
    is_live = False
    
    streammux = Gst.ElementFactory.make("nvstreammux", "Stream-muxer")
    pipeline.add(streammux)

    for i in range(number_sources):
        uri_name = args[i + 1]
        if uri_name.find("rtsp://") == 0: is_live = True
        source_bin = create_source_bin(i, uri_name)
        pipeline.add(source_bin)
        source_bin.get_static_pad("src").link(streammux.request_pad_simple(f"sink_{i}"))

    nvvidconv1 = Gst.ElementFactory.make("nvvideoconvert", "convertor1")
    caps1 = Gst.Caps.from_string("video/x-raw(memory:NVMM), format=RGBA")
    filter1 = Gst.ElementFactory.make("capsfilter", "filter1")
    filter1.set_property("caps", caps1)
    
    tiler = Gst.ElementFactory.make("nvmultistreamtiler", "nvtiler")
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "convertor")
    
    sink = Gst.ElementFactory.make("fakesink", "fakesink")
    if not sink:
        sys.stderr.write("Unable to create fakesink\n"); return False
        
    streammux.set_property('live-source', 1 if is_live else 0)
    streammux.set_property('width', MUXER_OUTPUT_WIDTH)
    streammux.set_property('height', MUXER_OUTPUT_HEIGHT)
    streammux.set_property('batch-size', number_sources)
    streammux.set_property('batched-push-timeout', MUXER_BATCH_TIMEOUT_USEC)
    
    tiler_rows = int(math.sqrt(number_sources))
    tiler.set_property("rows", tiler_rows)
    tiler.set_property("columns", int(math.ceil((1.0 * number_sources) / tiler_rows)))
    tiler.set_property("width", TILED_OUTPUT_WIDTH)
    tiler.set_property("height", TILED_OUTPUT_HEIGHT)

    mem_type = int(pyds.NVBUF_MEM_CUDA_UNIFIED)
    streammux.set_property("nvbuf-memory-type", mem_type)
    nvvidconv.set_property("nvbuf-memory-type", mem_type)
    tiler.set_property("nvbuf-memory-type", mem_type)
    
    if platform_info.is_integrated_gpu():
        nvvidconv1.set_property("nvbuf-memory-type", 4)
    else:
        nvvidconv1.set_property("nvbuf-memory-type", mem_type)

    sink.set_property("sync", 0)
    sink.set_property("qos", 0)

    pipeline.add(nvvidconv1)
    pipeline.add(filter1)
    pipeline.add(tiler)
    pipeline.add(nvvidconv)
    pipeline.add(sink)

    streammux.link(nvvidconv1)
    nvvidconv1.link(filter1)
    filter1.link(tiler)
    tiler.link(nvvidconv)
    nvvidconv.link(sink)

    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, loop)

    tiler_sink_pad = tiler.get_static_pad("sink")
    tiler_sink_pad.add_probe(Gst.PadProbeType.BUFFER, tiler_sink_pad_buffer_probe, 0)
    GLib.timeout_add(5000, perf_data.perf_print_callback)

    print("Starting DeepStream hardware pipeline...\n")
    pipeline.set_state(Gst.State.PLAYING)
    try:
        loop.run()
    except Exception as e:
        pass
        
    pipeline.set_state(Gst.State.NULL)
    
    try:
        cuda_context.pop()
    except Exception:
        pass
    cuda_context.detach()
    print("Pipeline exited cleanly.")

if __name__ == '__main__':
    sys.exit(main(sys.argv))
