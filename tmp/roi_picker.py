#!/usr/bin/env python3
"""
roi_picker.py - Interactive mouse-based coordinate picker for building
NVIDIA DeepStream nvdsanalytics config sections (ROI / line-crossing / direction).

Works with an RTSP stream, a video file, or a still image.

Usage:
    python3 roi_picker.py "rtsp://user:pass@ip:554/stream" [--width 1920 --height 1080]
    python3 roi_picker.py /path/to/video.mp4 [--width 1920 --height 1080]
    python3 roi_picker.py /path/to/snapshot.jpg [--width 1920 --height 1080]

Tip: match --width/--height to your streammux width/height (e.g. 1920x1080)
so the pixel coordinates you pick line up exactly with what nvdsanalytics sees.

Controls:
    SPACE        - play / pause the feed (pause on the frame you want to annotate)
    Left click   - add a point (only takes effect while paused)
    Right click  - remove last point
    n            - finish current shape, name it, choose its type, start a new shape
    u            - undo last point (same as right click)
    z            - delete the last completed shape
    s            - save all shapes to nvdsanalytics_snippet.txt (config-ready) and print
    r            - reset everything
    q / ESC      - quit (auto-saves if any shapes exist)
"""

import cv2
import argparse
import os
import time

POINT_COLOR = (0, 0, 255)      # red dots for points being placed
LINE_COLOR = (0, 255, 255)     # yellow while drawing
DONE_COLORS = [(0, 255, 0), (255, 0, 255), (255, 255, 0), (0, 128, 255), (255, 0, 0), (128, 0, 255)]


class Picker:
    def __init__(self, frame):
        self.base = frame
        self.frame_h, self.frame_w = frame.shape[:2]
        self.current_points = []
        self.shapes = []  # list of dict(name, type, points)
        self.mouse_pos = (0, 0)
        self.paused = False

    def set_frame(self, frame):
        self.base = frame

    def on_mouse(self, event, x, y, flags, param):
        self.mouse_pos = (x, y)
        if not self.paused:
            return  # ignore clicks while live to avoid accidental points
        if event == cv2.EVENT_LBUTTONDOWN:
            self.current_points.append((x, y))
            print(f"  point added: {x},{y}   (total in shape: {len(self.current_points)})")
        elif event == cv2.EVENT_RBUTTONDOWN:
            if self.current_points:
                p = self.current_points.pop()
                print(f"  removed point: {p}")

    def draw(self):
        img = self.base.copy()
        for i, shp in enumerate(self.shapes):
            color = DONE_COLORS[i % len(DONE_COLORS)]
            pts = shp["points"]
            for j in range(len(pts)):
                cv2.circle(img, pts[j], 4, color, -1)
                if j > 0:
                    cv2.line(img, pts[j - 1], pts[j], color, 2)
            if shp["type"] == "roi" and len(pts) > 2:
                cv2.line(img, pts[-1], pts[0], color, 2)
            if pts:
                cv2.putText(img, shp["name"], pts[0], cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        for j, p in enumerate(self.current_points):
            cv2.circle(img, p, 4, POINT_COLOR, -1)
            if j > 0:
                cv2.line(img, self.current_points[j - 1], p, LINE_COLOR, 2)
        if self.current_points:
            cv2.line(img, self.current_points[-1], self.mouse_pos, LINE_COLOR, 1)

        status = "PAUSED - click to add points" if self.paused else "LIVE - press SPACE to pause"
        status_color = (0, 255, 255) if self.paused else (0, 255, 0)
        hud = [
            f"[{status}]",
            "SPACE: play/pause   L-click: add point   R-click: undo point   n: finish shape",
            "z: delete last shape   s: save+print config   r: reset all   q/ESC: quit",
            f"cursor: {self.mouse_pos}   points in current shape: {len(self.current_points)}",
        ]
        cv2.putText(img, hud[0], (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, hud[0], (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, status_color, 1, cv2.LINE_AA)
        for i, line in enumerate(hud[1:], start=1):
            cv2.putText(img, line, (10, 20 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(img, line, (10, 20 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        return img

    def finish_shape(self):
        if len(self.current_points) < 2:
            print("Need at least 2 points to finish a shape.")
            return
        name = input("Name for this shape (e.g. Entry, Shelf, North): ").strip() or f"shape{len(self.shapes) + 1}"
        print("Type: [1] ROI polygon  [2] line-crossing  [3] direction-detection line")
        t = input("Choose 1/2/3: ").strip()
        type_map = {"1": "roi", "2": "line-crossing", "3": "direction"}
        shp_type = type_map.get(t, "roi")
        self.shapes.append({"name": name, "type": shp_type, "points": list(self.current_points)})
        self.current_points = []
        print(f"Shape '{name}' ({shp_type}) saved.\n")

    def delete_last_shape(self):
        if self.shapes:
            removed = self.shapes.pop()
            print(f"Deleted shape: {removed['name']}")

    def reset(self):
        self.shapes = []
        self.current_points = []
        print("All shapes cleared.")

    def to_config_text(self):
        lines = []
        for shp in self.shapes:
            coord_str = ";".join(f"{x};{y}" for x, y in shp["points"])
            name = shp["name"]
            if shp["type"] == "roi":
                lines += [f"[roi-{name}]", "enable=1", f"roi-{name}={coord_str}", "inverse-roi=0", "class-id=-1", ""]
            elif shp["type"] == "line-crossing":
                lines += [f"[line-crossing-{name}]", "enable=1", f"line-crossing-{name}={coord_str}",
                          "extended=0", "mode=loose", "class-id=-1", ""]
            elif shp["type"] == "direction":
                lines += [f"[direction-{name}]", "enable=1", f"direction-{name}={coord_str}", "class-id=-1", ""]
        return "\n".join(lines)

    def save(self, path="nvdsanalytics_snippet.txt"):
        text = self.to_config_text()
        with open(path, "w") as f:
            f.write(text)
        print("\n" + "=" * 60)
        print(f"Saved to {os.path.abspath(path)}")
        print("Paste the relevant section(s) into config_nvdsanalytics.txt")
        print("=" * 60)
        print(text)
        print("=" * 60)


def open_capture(source):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open source '{source}' (checked as RTSP/video/image via OpenCV).")
    return cap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="rtsp:// uri, video file path, or image file path")
    ap.add_argument("--width", type=int, default=None, help="resize width (match streammux width, e.g. 1920)")
    ap.add_argument("--height", type=int, default=None, help="resize height (match streammux height, e.g. 1080)")
    args = ap.parse_args()

    is_rtsp = args.source.lower().startswith("rtsp://")

    cap = open_capture(args.source)
    ok, frame = cap.read()
    if not ok:
        raise SystemExit(f"Could not read an initial frame from '{args.source}'")
    if args.width and args.height:
        frame = cv2.resize(frame, (args.width, args.height))

    picker = Picker(frame)

    win = "ROI / Line Picker (coords = this frame's pixel space)"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, picker.on_mouse)

    print(f"Frame size: {picker.frame_w}x{picker.frame_h}")
    print("Feed is LIVE. Press SPACE to pause on the frame you want, then click to annotate.\n")

    while True:
        if not picker.paused:
            ok, frame = cap.read()
            if not ok:
                if is_rtsp:
                    print("RTSP read failed, reconnecting...")
                    cap.release()
                    time.sleep(1)
                    cap = open_capture(args.source)
                    continue
                else:
                    # video file ended - loop back to start
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
            if args.width and args.height:
                frame = cv2.resize(frame, (args.width, args.height))
            picker.set_frame(frame)

        img = picker.draw()
        cv2.imshow(win, img)
        key = cv2.waitKey(20) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key == ord(' '):
            picker.paused = not picker.paused
            print("PAUSED" if picker.paused else "LIVE")
        elif key == ord('n'):
            picker.finish_shape()
        elif key == ord('u'):
            if picker.current_points:
                picker.current_points.pop()
        elif key == ord('z'):
            picker.delete_last_shape()
        elif key == ord('r'):
            picker.reset()
        elif key == ord('s'):
            picker.save()

    cap.release()
    cv2.destroyAllWindows()
    if picker.shapes:
        picker.save()


if __name__ == "__main__":
    main()

