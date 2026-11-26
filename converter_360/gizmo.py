"""Trackball rotation widget; matrices are converted to the existing v360 preset angles."""
import math
import tkinter as tk

import numpy as np

from .preview import rotation

# Blender-style world convention: X right, Y forward, Z up. The renderer uses y down.
AXES = {"X": np.array([1., 0., 0.]), "Y": np.array([0., 0., 1.]), "Z": np.array([0., -1., 0.])}
COLORS = {"X": "#ff637b", "Y": "#8bdb65", "Z": "#65a9ff"}


def axis_rotation(axis, degrees):
    x, y, z = axis / np.linalg.norm(axis)
    skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    a = math.radians(degrees)
    return np.eye(3) + math.sin(a) * skew + (1 - math.cos(a)) * (skew @ skew)


def to_angles(matrix):
    """RY(yaw) RX(pitch) RZ(roll), with a stable equivalent at either pole."""
    pitch = math.asin(float(np.clip(-matrix[1, 2], -1, 1)))
    if abs(math.cos(pitch)) > 1e-6:
        yaw = math.atan2(matrix[0, 2], matrix[2, 2])
        roll = math.atan2(matrix[1, 0], matrix[1, 1])
    else:
        yaw = math.atan2(-matrix[2, 0], matrix[0, 0])
        roll = 0
    return tuple(math.degrees(a) for a in (yaw, pitch, roll))


def ball_vector(x, y):
    length = math.hypot(x, y)
    if length > 1:
        return np.array([x / length, y / length, 0.])
    return np.array([x, y, math.sqrt(max(0, 1 - length * length))])


def trackball(start, end):
    # Inverse camera motion makes the panorama follow the pointer.
    axis = np.cross(end, start)
    length = np.linalg.norm(axis)
    dot = float(np.clip(np.dot(start, end), -1, 1))
    if length < 1e-10:
        if dot > 0:
            return np.eye(3)
        helper = np.eye(3)[np.argmin(np.abs(start))]
        return axis_rotation(np.cross(start, helper), 180)
    return axis_rotation(axis, math.degrees(math.atan2(length, dot)))


class RotationGizmo(tk.Canvas):
    def __init__(self, parent, on_change):
        super().__init__(parent, width=174, height=174, bg="#121d30", highlightthickness=1,
                         highlightbackground="#34455f", highlightcolor="#b6c8e2", takefocus=True,
                         cursor="hand2")
        self.on_change = on_change
        self.matrix = np.eye(3)
        self.mode = "Своб."
        self.gesture = None
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<B1-Motion>", self.move)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<MouseWheel>", self.wheel)
        self.bind("<KeyPress>", self.key)
        self.redraw()

    def geometry_values(self):
        size = max(100, self.winfo_width())
        return size / 2, (size - 32) / 2, (size - 42) / 2

    def set_angles(self, yaw, pitch, roll):
        self.matrix = rotation(yaw, pitch, roll).astype(float)
        self.redraw()

    def redraw(self):
        self.delete("all")
        cx, cy, radius = self.geometry_values()
        self.buttons = {}
        self.create_oval(cx-radius, cy-radius, cx+radius, cy+radius, fill="#1d2b43", outline="#51637d")
        # Split circles into depth-sorted segments, with muted rear halves.
        segments = []
        for name, normal in AXES.items():
            helper = np.eye(3)[np.argmin(np.abs(normal))]
            u = np.cross(normal, helper)
            v = np.cross(normal, u)
            angles = np.linspace(0, 2 * np.pi, 73)
            points = (self.matrix.T @ (u[:, None] * np.cos(angles) + v[:, None] * np.sin(angles))).T
            screen = [(cx + radius * p[0], cy + radius * p[1]) for p in points]
            for i in range(len(points)-1):
                depth = (points[i, 2] + points[i+1, 2]) / 2
                segments.append((depth, name, screen[i], screen[i+1]))
        for depth, name, a, b in sorted(segments, key=lambda item: item[0]):
            self.create_line(*a, *b, fill=COLORS[name] if depth >= 0 else "#42516b",
                             width=3 if self.mode == name else 2)
        # Axis labels move with the orientation; letters supplement the colors.
        ends = [(float((self.matrix.T @ vector)[2]), name, self.matrix.T @ vector) for name, vector in AXES.items()]
        for depth, name, p in sorted(ends, key=lambda item: item[0]):
            x, y = cx + radius * p[0], cy + radius * p[1]
            self.create_oval(x-10, y-10, x+10, y+10, fill=COLORS[name], outline="#101a2b")
            self.create_text(x, y, text=name, fill="#07101e", font=("Segoe UI", 9, "bold"))
        width = max(100, self.winfo_width())
        for i, name in enumerate(("Своб.", "X", "Y", "Z")):
            bounds = (i * width / 4 + 2, width - 28, (i+1) * width / 4 - 2, width - 3)
            self.buttons[name] = bounds
            self.create_rectangle(*bounds, fill="#34455f" if self.mode == name else "#19263a",
                                  outline=COLORS.get(name, "#b6c8e2") if self.mode == name else "#34455f")
            self.create_text((bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2, text=name,
                             fill=COLORS.get(name, "#dce7f7"), font=("Segoe UI", 9, "bold"))

    def press(self, event):
        self.focus_set()
        for name, (x0, y0, x1, y1) in self.buttons.items():
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self.mode = name
                self.redraw()
                return
        cx, cy, radius = self.geometry_values()
        if math.hypot(event.x-cx, event.y-cy) > radius + 10:
            return
        # Rings and moving axis labels are visual guides, not mode switches.
        # Axis locking must be an explicit button/keyboard action.
        axis = self.mode if self.mode in AXES else None
        self.gesture = (event.x, event.y, self.matrix.copy(), axis)

    def move(self, event):
        if self.gesture is None:
            return
        x, y, initial, axis = self.gesture
        sensitivity = 0.1 if event.state & 1 else 0.5
        if axis:
            # Horizontal drag has the same meaning even when a ring is edge-on.
            self.matrix = axis_rotation(AXES[axis], (event.x-x - event.y+y) * sensitivity) @ initial
        else:
            cx, cy, radius = self.geometry_values()
            factor = 0.2 if event.state & 1 else 1
            start = ball_vector((x-cx)/radius, (y-cy)/radius)
            end = ball_vector((x-cx+(event.x-x)*factor)/radius, (y-cy+(event.y-y)*factor)/radius)
            self.matrix = initial @ trackball(start, end)
        self.redraw()
        self.on_change(self.matrix, True)

    def release(self, event):
        if self.gesture is not None:
            self.move(event)
            self.gesture = None
            self.on_change(self.matrix, False)

    def step(self, amount, axis=None):
        self.matrix = axis_rotation(AXES[axis or (self.mode if self.mode in AXES else "Z")], amount) @ self.matrix
        self.redraw()
        self.on_change(self.matrix, False)

    def wheel(self, event):
        if event.delta:
            self.step((0.25 if event.state & 1 else 2) * event.delta / 120)
        return "break"

    def key(self, event):
        key = event.keysym.lower()
        if key in ("x", "y", "z", "f"):
            self.mode = "Своб." if key == "f" else key.upper()
            self.redraw()
        elif key in ("left", "right", "up", "down"):
            self.step((0.25 if event.state & 1 else 2) * (-1 if key in ("left", "down") else 1),
                      "X" if self.mode == "Своб." and key in ("up", "down") else None)
        elif key == "home":
            self.gesture = None
            self.matrix = np.eye(3)
            self.redraw()
            self.on_change(self.matrix, False)
        elif key == "escape" and self.gesture is not None:
            self.matrix = self.gesture[2]
            self.gesture = None
            self.redraw()
            self.on_change(self.matrix, False)
        else:
            return None  # Keep Tab navigation.
        return "break"
