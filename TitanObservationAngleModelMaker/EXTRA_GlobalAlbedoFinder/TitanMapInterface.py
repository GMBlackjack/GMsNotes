import sys
import os
import json
import csv
import numpy as np
import awkward as ak
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QScrollArea, QColorDialog, QFrame, QSizePolicy)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import warnings
from PIL import Image

# Suppress runtime warnings from numpy median calculations on empty slices
warnings.filterwarnings("ignore", category=RuntimeWarning)

# --- GLOBAL CONFIGURATION ---
CUBE_DATABASE_PATH = "C:\\Users\\deran\\Desktop\\CubeCSVDatabase\\"

class TitanDataModel:
    def __init__(self):
        print("Loading Parquet Data... (This may take a moment)")
        self.globalIoF = ak.from_parquet("globalRetrievedIFALLRev.parquet")
        self.globalAlbedos = ak.from_parquet("globalRetrievedAlbedosALLRev.parquet")
        self.globalObsAngles = ak.from_parquet("globalRetrievedObsAnglesALLRev.parquet")
        self.globalCubeList = ak.from_parquet("globalRetrievedCubeListALLRev.parquet")
        
        self.map_file = "TitanTerrains.titanMap.npy"
        if os.path.exists(self.map_file): self.titanMap = np.load(self.map_file)
        else: self.titanMap = np.full((181, 360), "UNSET!", dtype=object)

        self.mask_file = "CLRMaskArray.npy"
        if os.path.exists(self.mask_file): self.CLRMask = np.load(self.mask_file)
        else: self.CLRMask = np.zeros((181, 360, 3))

        # Reverted to the correct 181-element array
        self.binSize = [
            360, 30, 20, 15, 12, 10, 8, 6, 6, 5,
            5, 4, 4, 4, 3, 3, 3, 3, 3, 2, 
            2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 
            1, # at 0 here 
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
            2, 3, 3, 3, 3, 3, 4, 4, 4, 5, 
            5, 6, 6, 8, 10, 12, 15, 20, 30, 360
        ]
        
        self.wavText = ["1.27um", "1.59um", "2.01um", "2.69um", "2.79um", "5.00um"]
        self.wavTextFull = ["Color", "0.93um", "1.08um", "1.27um", "1.59um", "2.01um", "2.69um", "2.79um", "5.00um"]
        
        self.color_file = "terrain_colors.json"
        self.terrain_colors = {}
        self.rng = np.random.default_rng()
        self.load_colors()

        # V2: Cube Tracking & Caching
        self.cube_cache = {} # Stores processed images and geo grids
        self.cube_ref = {}
        self.load_cube_references()

        self.real_map_file = "TitanCompareMap.png" # Change this to your exact filename
        if os.path.exists(self.real_map_file):
            # 1. Open with PIL and force RGB (removes transparency/alpha channels safely)
            img = Image.open(self.real_map_file).convert('RGB')
            
            # 2. Resize to exactly match our Titan array dimensions (Width x Height)
            img = img.resize((360, 181))
            
            # 3. Convert to numpy array and normalize values to 0.0 - 1.0 for Matplotlib
            self.real_img_data = np.array(img) / 255.0
        else:
            self.real_img_data = None

    def get_predicted_terrain(self, inY, inX):
        if inY == 180: inY = 179 
        if inX == 360: return "Null" 

        val = self.CLRMask[inY][inX]
        if val[0] == 0:
            if val[1] == 0: return "Null" if val[2] == 0 else "Lake"
            else: return "Xanadu" if val[2] == 0 else "Crater"
        else:
            if val[1] == 0: return "Dunes" if val[2] == 0 else "Labyrinth"
            else: return "Hummocky" if val[2] == 0 else "Plains"

    def load_colors(self):
        if os.path.exists(self.color_file):
            with open(self.color_file, 'r') as f:
                self.terrain_colors = json.load(f)
        
        unique_terrains = np.unique(self.titanMap)
        changed = False
        for t in unique_terrains:
            if t not in self.terrain_colors:
                if t == "UNSET!": self.terrain_colors[t] = [1.0, 1.0, 1.0]
                elif t == "VOID!": self.terrain_colors[t] = [0.0, 0.0, 0.0]
                else: self.terrain_colors[t] = [self.rng.random(), self.rng.random(), self.rng.random()]
                changed = True
        if changed: self.save_colors()

    def save_colors(self):
        with open(self.color_file, 'w') as f: json.dump(self.terrain_colors, f, indent=4)

    def save_map(self):
        np.save(self.map_file, self.titanMap)

    def load_cube_references(self):
        try:
            with open("..\\DatabaseSearcher\\AcceptableCubes.csv", 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    flyby_str = row[0]
                    cube_str = row[1]
                    if flyby_str == "TA": flyby = 1
                    elif flyby_str == "TB": flyby = 2
                    else: flyby = int(flyby_str[1:])
                    self.cube_ref[cube_str] = flyby
        except FileNotFoundError:
            print("Warning: AcceptableCubes.csv not found in current directory.")

    def fetch_cube_data(self, cube_id):
        # 1. Check Cache
        if cube_id in self.cube_cache:
            return self.cube_cache[cube_id]

        # 2. Setup Paths
        flyby = self.cube_ref.get(cube_id, 0)
        f_dir = "TA" if flyby == 1 else "TB" if flyby == 2 else f"T{flyby}"
        base_path = os.path.join(CUBE_DATABASE_PATH, f_dir, f"CM_{cube_id}")
        
        fp_data = base_path + ".cub.csv"
        fp_axes = base_path + ".cub.axes.csv"
        fp_geo = base_path + "_ir_geo.cub.csv"
        fp_geo_axes = base_path + "_ir_geo.cub.axes.csv"

        if not os.path.exists(fp_data):
            print(f"ERROR: Could not find file at -> {fp_data}")
            return None

        # 3. Read Axes (To get exact shapes for reshaping)
        def get_dims(path):
            with open(path, 'r') as f:
                lines = f.readlines()
                return [len([v for v in lines[i].split(',') if v.strip()]) for i in range(3)]
        
        x_len, y_len, z_len = get_dims(fp_axes)
        gx_len, gy_len, gz_len = get_dims(fp_geo_axes)

        # 4. Load & Reshape Data (Significantly faster than nested while loops)
        raw_data = np.genfromtxt(fp_data, delimiter=',')
        temp = raw_data[:, :x_len].reshape((z_len, y_len, x_len))
        temp = np.nan_to_num(temp, nan=0.0)
        temp[temp < 0] = 0
        temp[temp > 1] = 1

        raw_geo = np.genfromtxt(fp_geo, delimiter=',')
        geo_temp = raw_geo[:, :gx_len].reshape((gz_len, gy_len, gx_len))
        geo_temp = np.nan_to_num(geo_temp, nan=0.0)
        geo_temp[geo_temp < -1000] = 0

        # 5. Extract specific wavelengths and RGB (Matching original math)
        ofs = 0 if z_len > 256 else 96
        ave = np.sum(temp[336-ofs : 352-ofs], axis=0) / 16.0
        
        R = ave / (1.0 * 1.12 / 16.0)
        G = temp[165-ofs] / 0.22
        B = (temp[120-ofs] - 0.03) / 0.37
        B[B < 0] = 0
        
        colorData = np.transpose(np.array([R, G, B])) # Arranged in X, Y, 3

        # Stack contains [Color, 0.93, 1.08, 1.27, 1.59, 2.01, 2.69, 2.79, 5.00]
        cubeStack = [
            colorData,
            np.transpose(temp[99-ofs]),
            np.transpose(temp[108-ofs]),
            np.transpose(temp[120-ofs]),
            np.transpose(temp[139-ofs]),
            np.transpose(temp[165-ofs]),
            np.transpose(temp[206-ofs]),
            np.transpose(temp[212-ofs]),
            np.transpose(ave)
        ]

        # 6. Save to cache
        result = {'images': cubeStack, 'lat': geo_temp[0], 'lon': geo_temp[1], 'flyby': flyby}
        self.cube_cache[cube_id] = result
        return result

    def get_highlights(self, cube_id, lat_target, lon_start, lon_end):
        data = self.cube_cache.get(cube_id)
        if not data: return [], []
        
        LAT = data['lat']
        LON = data['lon']

        mask_lat = (LAT >= lat_target - 0.5) & (LAT <= lat_target + 0.5)
        mask_lon = (LON >= lon_start - 0.5) & (LON <= lon_end + 0.5)
        if lon_end == 360: # Special fat pixel logic for wrap around
            mask_lon = mask_lon | ((LON >= -0.5) & (LON <= 0.5))

        # np.where returns rows (Y) then columns (X).
        y_idx, x_idx = np.where(mask_lat & mask_lon)
        
        # Return X first, then Y, without the 0.5 offset so they sit dead center.
        return y_idx, x_idx


class CubePopupWindow(QWidget):
    def __init__(self, data_model, cube_ids, lat, start_lon, end_lon):
        super().__init__()
        self.setWindowTitle("Cube Display Interface")
        self.setGeometry(150, 150, 800, 800)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        self.data_model = data_model
        self.cube_ids = cube_ids
        self.lat = lat
        self.start_lon = start_lon
        self.end_lon = end_lon
        
        self.current_cube_idx = 0
        self.current_wav_idx = 0
        
        self.init_ui()
        self.update_display()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.fig, self.ax = plt.subplots(figsize=(8, 8), layout="constrained")
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.canvas)

        # Matplotlib eats keyboard inputs, so we hook into it
        self.canvas.mpl_connect('key_press_event', self.on_key_press)
        self.canvas.mpl_connect('button_press_event', lambda e: self.canvas.setFocus())

    def on_key_press(self, event):
        key = event.key
        moved = False
        
        if key == 'left':
            self.current_cube_idx = (self.current_cube_idx - 1) % len(self.cube_ids)
            moved = True
        elif key == 'right':
            self.current_cube_idx = (self.current_cube_idx + 1) % len(self.cube_ids)
            moved = True
        elif key == 'up':
            self.current_wav_idx = (self.current_wav_idx - 1) % 9
            moved = True
        elif key == 'down':
            self.current_wav_idx = (self.current_wav_idx + 1) % 9
            moved = True
            
        if moved: self.update_display()

    def update_display(self):
        self.ax.clear()
        
        cube_id = self.cube_ids[self.current_cube_idx]
        cube_data = self.data_model.cube_cache[cube_id]
        
        # 1. Draw Image
        img = cube_data['images'][self.current_wav_idx]
        cmap = "copper" if self.current_wav_idx > 0 else None
        
        h, w = img.shape[:2]
        self.ax.imshow(img, cmap=cmap)
        self.ax.set_xlim(-0.5, w - 0.5)
        self.ax.set_ylim(h - 0.5, -0.5)
        self.ax.set_box_aspect(h/w)

        # 2. Draw Cyan Highlight Dots
        hx, hy = self.data_model.get_highlights(cube_id, self.lat, self.start_lon, self.end_lon)
        if len(hx) > 0:
            self.ax.scatter(hx, hy, marker=".", color="cyan", s=10)

        # 3. Setup Title
        flyby = cube_data['flyby']
        f_str = "TA" if flyby == 1 else "TB" if flyby == 2 else f"T{flyby}"
        wav_str = self.data_model.wavTextFull[self.current_wav_idx]
        title = f"{f_str} {cube_id} {wav_str} Cube {self.current_cube_idx + 1} of {len(self.cube_ids)}"
        
        self.ax.set_title(title, size=11, fontweight="bold")
        self.ax.axis('off')
        self.canvas.draw_idle()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Titan Surface Analyzer V2.0")
        self.setGeometry(100, 100, 1400, 900)
        
        self.data = TitanDataModel()
        
        self.inY = 90
        self.anchor_lon = 180 
        self.current_lat = 0
        self.start_lon = 180
        self.end_lon = 180
        self.inX_start = 180
        self.inX_end = 180
        self.current_unique_cubes = []
        self.popup = None # Keep reference to prevent garbage collection
        self.show_real_map = False

        self.plot_timer = QTimer()
        self.plot_timer.setSingleShot(True)
        self.plot_timer.timeout.connect(self.update_stats)

        self.init_ui()
        self.calculate_bounds()
        self.update_map_visuals()
        self.update_stats()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # --- TOP HALF: Map and Legend ---
        top_layout = QHBoxLayout()
        
        self.fig_map, self.ax_map = plt.subplots(figsize=(10, 4), layout="constrained")
        self.canvas_map = FigureCanvas(self.fig_map)
        self.canvas_map.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas_map.setFocusPolicy(Qt.FocusPolicy.StrongFocus) 
        self.ax_map.axis('off')
        self.canvas_map.mpl_connect('button_press_event', lambda event: self.canvas_map.setFocus())
        self.canvas_map.mpl_connect('key_press_event', self.on_map_key_press)
        top_layout.addWidget(self.canvas_map, stretch=4)
        
        # Create a right-side panel layout
        right_panel = QVBoxLayout()
        
        # Add the new toggle button
        self.btn_toggle_map = QPushButton("Show Real Map")
        self.btn_toggle_map.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_toggle_map.clicked.connect(self.toggle_real_map)
        right_panel.addWidget(self.btn_toggle_map)
        
        # Setup and add the legend below the button
        self.legend_scroll = QScrollArea()
        self.legend_scroll.setWidgetResizable(True)
        self.legend_content = QWidget()
        self.legend_layout = QVBoxLayout(self.legend_content)
        self.legend_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.legend_scroll.setWidget(self.legend_content)
        right_panel.addWidget(self.legend_scroll)
        
        # Add the whole panel to the top layout
        top_layout.addLayout(right_panel, stretch=1)
        
        self.build_legend()
        main_layout.addLayout(top_layout, stretch=1)

        # --- BOTTOM HALF: Stats and Controls ---
        bottom_layout = QHBoxLayout()
        
        plotLayout = [
            ["IoF", "Albedo", "Inci"],
            ["IoF", "Albedo", "Emis"],
            ["IoF", "Albedo", "Azim"]
        ]
        self.fig_stats, self.axs_stats = plt.subplot_mosaic(plotLayout, figsize=(10, 5), layout="constrained")
        self.canvas_stats = FigureCanvas(self.fig_stats)
        bottom_layout.addWidget(self.canvas_stats, stretch=4)

        # Controls Panel
        controls_layout = QVBoxLayout()
        controls_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.lbl_current_terrain = QLabel("Current: UNSET!")
        self.lbl_current_terrain.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        self.txt_terrain_edit = QLineEdit()
        self.txt_terrain_edit.setMaxLength(6)
        self.txt_terrain_edit.setPlaceholderText("NEW TAG")
        self.txt_terrain_edit.returnPressed.connect(self.assign_terrain) 
        
        self.btn_update = QPushButton("Update Terrain")
        self.btn_update.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_update.clicked.connect(self.assign_terrain)
        
        self.lbl_predicted_terrain = QLabel("Predicted: --")
        self.lbl_predicted_terrain.setStyleSheet("font-style: italic; color: gray;")
        
        self.lbl_high_iof = QLabel("HIGH I/F: --")
        self.lbl_low_iof = QLabel("LOW I/F: --")
        self.lbl_cubes = QLabel("CUBES: --")
        
        self.btn_cubes = QPushButton("Display Cubes")
        self.btn_cubes.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_cubes.clicked.connect(self.open_cube_popup)
        self.btn_cubes.setEnabled(False) 
        
        controls_layout.addWidget(self.lbl_current_terrain)
        controls_layout.addWidget(self.txt_terrain_edit)
        controls_layout.addWidget(self.btn_update)
        controls_layout.addWidget(self.lbl_predicted_terrain)
        controls_layout.addWidget(self.lbl_high_iof)
        controls_layout.addWidget(self.lbl_low_iof)
        controls_layout.addWidget(self.lbl_cubes)
        self.fig_zoom, self.ax_zoom = plt.subplots(figsize=(2.5, 2.5), layout="constrained")
        self.canvas_zoom = FigureCanvas(self.fig_zoom)
        self.canvas_zoom.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.canvas_zoom.setFixedSize(200, 200) # Forces it to stay a compact square
        self.ax_zoom.axis('off')
        controls_layout.addWidget(self.canvas_zoom, alignment=Qt.AlignmentFlag.AlignCenter)
        controls_layout.addSpacing(10)
        controls_layout.addWidget(self.btn_cubes)
        
        bottom_layout.addLayout(controls_layout, stretch=1)
        main_layout.addLayout(bottom_layout, stretch=1)

    def build_legend(self):
        for i in reversed(range(self.legend_layout.count())): 
            self.legend_layout.itemAt(i).widget().setParent(None)
            
        for name, color in self.data.terrain_colors.items():
            btn = QPushButton(name)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            r, g, b = [int(c * 255) for c in color]
            text_color = "black" if (r*0.299 + g*0.587 + b*0.114) > 186 else "white"
            btn.setStyleSheet(f"background-color: rgb({r},{g},{b}); color: {text_color}; font-weight: bold; padding: 5px;")
            btn.clicked.connect(lambda checked, n=name: self.change_color(n))
            self.legend_layout.addWidget(btn)

    def change_color(self, terrain_name):
        current_color = self.data.terrain_colors[terrain_name]
        init_color = QColor(int(current_color[0]*255), int(current_color[1]*255), int(current_color[2]*255))
        new_color = QColorDialog.getColor(init_color, self, f"Pick Color for {terrain_name}")
        
        if new_color.isValid():
            self.data.terrain_colors[terrain_name] = [new_color.red()/255, new_color.green()/255, new_color.blue()/255]
            self.data.save_colors()
            self.build_legend()
            self.update_map_visuals()

    def assign_terrain(self):
        new_tag = self.txt_terrain_edit.text().strip()
        if not new_tag: return
            
        if new_tag not in self.data.terrain_colors:
            self.data.terrain_colors[new_tag] = [self.data.rng.random(), self.data.rng.random(), self.data.rng.random()]
            self.data.save_colors()
            self.build_legend()
            
        width = self.inX_start - self.inX_end + 1
        for i in range(width):
            target_inX = self.inX_end + i
            self.data.titanMap[self.inY][target_inX] = new_tag
            
        self.data.save_map()
        self.update_map_visuals()
        self.lbl_current_terrain.setText(f"Current: {new_tag}")
        self.canvas_map.setFocus()

    def calculate_bounds(self):
        self.current_lat = 90 - self.inY
        bin_size = self.data.binSize[self.current_lat + 90]
        
        chunk_index = int((self.anchor_lon - 1) / bin_size)
        self.start_lon = chunk_index * bin_size + 1
        self.end_lon = self.start_lon + bin_size - 1
        
        if self.end_lon > 360: self.end_lon = 360
        
        self.inX_start = 360 - self.start_lon
        self.inX_end = 360 - self.end_lon
        
        self.lbl_current_terrain.setText(f"Current: {self.data.titanMap[self.inY][self.inX_start]}")
        self.lbl_predicted_terrain.setText(f"Predicted: {self.data.get_predicted_terrain(self.inY, self.inX_start)}")

    def on_map_key_press(self, event):
        key = event.key
        moved = False
        
        if key == 'left': 
            self.anchor_lon += self.data.binSize[self.current_lat + 90]
            if self.anchor_lon > 360: self.anchor_lon -= 360
            moved = True
        elif key == 'right': 
            self.anchor_lon -= self.data.binSize[self.current_lat + 90]
            if self.anchor_lon < 1: self.anchor_lon += 360
            moved = True
        elif key == 'up': 
            if self.inY > 0:
                self.inY -= 1
                moved = True
        elif key == 'down': 
            if self.inY < 180:
                self.inY += 1
                moved = True
                
        if moved:
            self.calculate_bounds()
            self.update_map_visuals()
            self.plot_timer.start(150)

    def update_map_visuals(self):
        self.ax_map.clear()
        
        # 1. Decide which base array to use for the main map
        if self.show_real_map and self.data.real_img_data is not None:
            base_rgb = self.data.real_img_data
        else:
            base_rgb = np.zeros((181, 360, 3))
            for y in range(181):
                for x in range(360):
                    tag = self.data.titanMap[y][x]
                    base_rgb[y][x] = self.data.terrain_colors.get(tag, [1,1,1])
                    
        self.ax_map.imshow(base_rgb)
        
        # 2. Draw Receptacle
        width = self.inX_start - self.inX_end + 1
        rect = patches.Rectangle((self.inX_end - 0.5, self.inY - 0.5), width, 1, 
                                 linewidth=0.5, edgecolor='cyan', facecolor='none')
        self.ax_map.add_patch(rect)
        self.ax_map.set_title(f"Map View | Lat: {self.current_lat}° | Lon: {self.start_lon}-{self.end_lon}°")
        self.canvas_map.draw_idle()
        
        # 3. Zoom Map Logic
        self.ax_zoom.clear()
        zoom_map = np.ones((11, 11, 3)) 
        center_X = self.inX_end + (width - 1) // 2
        
        for dy in range(-5, 6):
            for dx in range(-5, 6):
                target_Y = self.inY + dy
                target_X = center_X + dx
                
                if 0 <= target_Y < 181 and 0 <= target_X < 360:
                    if self.show_real_map and self.data.real_img_data is not None:
                        # Grab color from the real image
                        zoom_map[dy+5][dx+5] = self.data.real_img_data[target_Y][target_X]
                    else:
                        # Grab color from our generated terrain map
                        tag = self.data.titanMap[target_Y][target_X]
                        zoom_map[dy+5][dx+5] = self.data.terrain_colors.get(tag, [1, 1, 1])
                        
        self.ax_zoom.imshow(zoom_map)
        
        # 4. Draw Zoom Receptacle
        zoom_x_start = self.inX_end - center_X + 5 
        rect_zoom = patches.Rectangle((zoom_x_start - 0.5, 5 - 0.5), width, 1, 
                                      linewidth=1.5, edgecolor='cyan', facecolor='none')
        self.ax_zoom.add_patch(rect_zoom)
        self.ax_zoom.set_title("Zoom View", size=10, fontweight="bold")
        self.ax_zoom.axis('off')
        self.canvas_zoom.draw_idle()

    def update_stats(self):
        for ax in self.axs_stats.values(): ax.clear()

        lat_idx = self.current_lat + 90
        start_lon_idx = 360 - self.start_lon
        width = self.inX_start - self.inX_end + 1
        
        medianIoF, madIoF = [0] * 6, [0] * 6
        medianAlbedo, madAlbedo = [0] * 6, [0] * 6
        inciDist, emisDist, azimDist = [], [], []
        unique_cubes = set()

        for wav in range(6):
            actual_wav = wav + 2 
            iof_buffer, albedo_buffer = [], []
            
            for i in range(width):
                target_lon_idx = start_lon_idx - i
                try:
                    for item in self.data.globalIoF[lat_idx][target_lon_idx][actual_wav]: iof_buffer.append(item)
                    for item in self.data.globalAlbedos[lat_idx][target_lon_idx][actual_wav]: albedo_buffer.append(item)
                    if wav == 0: # Only count cubes and angles once
                        for cube in self.data.globalCubeList[lat_idx][target_lon_idx]: unique_cubes.add(cube)
                        for item in self.data.globalObsAngles[lat_idx][target_lon_idx][0]: inciDist.append(item)
                        for item in self.data.globalObsAngles[lat_idx][target_lon_idx][1]: emisDist.append(item)
                        for item in self.data.globalObsAngles[lat_idx][target_lon_idx][2]: azimDist.append(item)
                except Exception: pass
            
            medianIoF[wav] = np.nanmedian(iof_buffer) if iof_buffer else np.nan
            madIoF[wav] = np.nanmedian(np.abs(iof_buffer - medianIoF[wav])) * 1.4826 if iof_buffer else np.nan
            
            medianAlbedo[wav] = np.nanmedian(albedo_buffer) if albedo_buffer else np.nan
            madAlbedo[wav] = np.nanmedian(np.abs(albedo_buffer - medianAlbedo[wav])) * 1.4826 if albedo_buffer else np.nan

        azimDist = np.array(azimDist) * (180 / np.pi)

        # Plot Data
        cmap = plt.colormaps["RdYlGn_r"]
        relErrIoF = np.clip(np.array(madIoF) / np.array(medianIoF), 0, 1)
        relErrAlbedo = np.clip(np.array(madAlbedo) / np.array(medianAlbedo), 0, 1)

        self.axs_stats["IoF"].barh(self.data.wavText, medianIoF, xerr=madIoF, error_kw={"capsize": 5}, color=cmap(relErrIoF))
        self.axs_stats["IoF"].invert_yaxis()
        self.axs_stats["IoF"].set_xlim(left=0)
        self.axs_stats["IoF"].set_title("Median I/F", size=11)
        self.axs_stats["IoF"].tick_params(top=True, labeltop=True)

        self.axs_stats["Albedo"].barh(self.data.wavText, medianAlbedo, xerr=madAlbedo, error_kw={"capsize": 5}, color=cmap(relErrAlbedo))
        self.axs_stats["Albedo"].barh(self.data.wavText, np.array(medianAlbedo) * -1, color="magenta")
        self.axs_stats["Albedo"].invert_yaxis()
        self.axs_stats["Albedo"].set_xlim(left=0)
        self.axs_stats["Albedo"].set_title("Median Retrieved Albedo", size=11)
        self.axs_stats["Albedo"].tick_params(top=True, labeltop=True)

        if inciDist: self.axs_stats["Inci"].hist(inciDist, range=(0, 100), bins=40, color='gray')
        self.axs_stats["Inci"].set_title("Incidence Angle", size=11)
        
        if emisDist: self.axs_stats["Emis"].hist(emisDist, range=(0, 90), bins=38, color='gray')
        self.axs_stats["Emis"].set_title("Emission Angle", size=11)
        
        if len(azimDist) > 0: self.axs_stats["Azim"].hist(azimDist, range=(0, 180), bins=38, color='gray')
        self.axs_stats["Azim"].set_title("Azimuth Angle", size=11)

        valid_iofs = [val for val in medianIoF if val != 0] 
        self.lbl_high_iof.setText(f"HIGH I/F: {max(valid_iofs):.4f}" if valid_iofs else "HIGH I/F: N/A")
        self.lbl_low_iof.setText(f"LOW I/F: {min(valid_iofs):.4f}" if valid_iofs else "LOW I/F: N/A")

        self.current_unique_cubes = sorted(list(unique_cubes))
        cube_count = len(self.current_unique_cubes)
        self.lbl_cubes.setText(f"CUBES: {cube_count}")
        
        self.btn_cubes.setText(f"Display Cubes ({cube_count})")
        self.btn_cubes.setEnabled(cube_count > 0)

        self.canvas_stats.draw_idle()

    def open_cube_popup(self):
        if self.popup is not None:
            self.popup.close()
            
        self.btn_cubes.setText("Loading Cubes...")
        self.btn_cubes.setEnabled(False)
        QApplication.processEvents() # Force UI to update button text before freezing

        valid_cubes = []
        for cube_id in self.current_unique_cubes:
            if self.data.fetch_cube_data(cube_id) is not None:
                valid_cubes.append(cube_id)
        
        if valid_cubes:
            self.popup = CubePopupWindow(self.data, valid_cubes, self.current_lat, self.start_lon, self.end_lon)
            self.popup.show()
            self.popup.canvas.setFocus()
            
        self.btn_cubes.setText(f"Display Cubes ({len(self.current_unique_cubes)})")
        self.btn_cubes.setEnabled(True)

    def closeEvent(self, event):
        # If the popup exists and is open, close it when the main window closes
        if self.popup is not None:
            self.popup.close()
            
        # Accept the event to allow the main window to close normally
        event.accept()

    def toggle_real_map(self):
        # 1. Check if the image actually exists in memory
        if self.data.real_img_data is None:
            print("ERROR: Cannot toggle map! 'titan_real_map.png' was not found or failed to load.")
            self.btn_toggle_map.setText("IMAGE MISSING")
            self.btn_toggle_map.setStyleSheet("color: red; font-weight: bold;")
            return # Stop the function here
            
        # 2. Normal toggle logic
        self.show_real_map = not self.show_real_map
        self.btn_toggle_map.setText("Show Terrain Map" if self.show_real_map else "Show Real Map")
        
        self.update_map_visuals()
        self.canvas_map.setFocus()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())