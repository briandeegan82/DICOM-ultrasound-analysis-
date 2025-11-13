#!/usr/bin/env python3
"""
Image Viewer with Bounding Box Overlay
A GUI application to load PNG files and display bounding boxes from YAML configuration.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
import yaml
import csv
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

try:
    from PIL import Image, ImageTk
    import numpy as np
except ImportError as e:
    print(f"Error: Missing required library. Please install: pip install pillow numpy pyyaml")
    print(f"Missing: {e.name}")
    exit(1)


class ImageViewer:
    """GUI application for viewing images with bounding box overlays."""
    
    def __init__(self, root: tk.Tk, config_path: str = "config/us_config.yaml"):
        """
        Initialize the image viewer.
        
        Args:
            root: Tkinter root window
            config_path: Path to YAML configuration file
        """
        self.root = root
        self.root.title("Image Viewer with Bounding Boxes")
        self.root.geometry("1400x1000")  # Taller window for 1.5x image pane
        
        self.config_path = Path(config_path)
        self.current_image: Optional[Image.Image] = None
        self.current_image_path: Optional[Path] = None
        self.photo: Optional[ImageTk.PhotoImage] = None
        self.config: Dict[str, Any] = {}
        
        # Colors for different boxes
        self.box_colors = {
            'bounding_box': 'red',
            'centerline_box': 'blue'
        }
        
        # Brown line color (#b27121 = RGB(178, 113, 33))
        self.brown_line_color = (178, 113, 33)
        self.brown_line_tolerance = 20  # Color matching tolerance
        self.detected_line_segments: list = []  # Store detected line segments
        
        # Vertical analysis lines
        self.analysis_line1_x = tk.IntVar(value=0)
        self.analysis_line2_x = tk.IntVar(value=0)
        self.analysis_line_color = 'yellow'
        
        # Area calculation results
        self.area_above = 0  # Positive flow area
        self.area_below = 0  # Negative flow area
        self.centerline_y = None  # Y coordinate of centerline (average)
        self.above_mask = None  # Mask for area above centerline (in analysis region coordinates)
        self.below_mask = None  # Mask for area below centerline (in analysis region coordinates)
        self.analysis_region_coords = None  # (x_min, y_min, x_max, y_max) for analysis region
        
        # Measurement results table
        self.measurement_counter = 0  # Counter for measurement rows
        
        # Axis marker mask
        self.axis_marker_mask = None  # Mask to exclude axis markers from calculations
        self.pixels_per_second = None  # Calculated from taller marker spacing (1 second apart)
        self.taller_markers_x = []  # X positions of taller markers (2x12)
        
        # Velocity markers (vertical markers on right edge of bounding box)
        self.velocity_marker_mask = None  # Mask for velocity markers (highlighted in orange)
        self.velocity_markers_y = []  # Y positions of velocity markers
        self.cm_per_second_per_pixel = None  # Calculated cm/s per pixel in Y direction
        self.cms_between_markers = tk.StringVar(value="50")  # User input: cm/s between markers
        
        # Area conversion will use existing calibrations:
        # X direction: pixels → seconds (using pixels_per_second)
        # Y direction: pixels → cm/s (using cm_per_second_per_pixel)
        # Result: area in px² → (seconds × cm/s) = cm
        
        self.setup_ui()
        self.load_config()
    
    def setup_ui(self):
        """Set up the user interface."""
        # Create menu bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Load PNG...", command=self.load_image, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        
        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Reload Config", command=self.load_config)
        view_menu.add_command(label="Refresh Image", command=self.refresh_image)
        
        # Bind keyboard shortcuts
        self.root.bind('<Control-o>', lambda e: self.load_image())
        
        # Create main frame
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create top section with image pane (1.5x taller)
        image_section = tk.Frame(main_frame)
        image_section.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Create canvas with scrollbars
        canvas_frame = tk.Frame(image_section)
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Canvas for image display
        self.canvas = tk.Canvas(canvas_frame, bg="gray", cursor="crosshair")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Vertical scrollbar
        v_scrollbar = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.configure(yscrollcommand=v_scrollbar.set)
        
        # Horizontal scrollbar for image
        h_scrollbar = tk.Scrollbar(image_section, orient=tk.HORIZONTAL, command=self.canvas.xview)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.configure(xscrollcommand=h_scrollbar.set)
        
        # Right panel with controls
        right_panel = tk.Frame(image_section, width=300)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(5, 0))
        
        # Top row: Analysis Lines and Actions side by side
        top_row = tk.Frame(right_panel)
        top_row.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        
        # Left: Analysis Lines
        left_col = tk.LabelFrame(top_row, text="Analysis Lines", padx=5, pady=5)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        
        # Line 1 controls
        line1_frame = tk.Frame(left_col)
        line1_frame.pack(fill=tk.X, pady=2)
        tk.Label(line1_frame, text="Line 1 X:").pack(side=tk.LEFT, padx=2)
        self.line1_entry = tk.Entry(line1_frame, width=6)
        self.line1_entry.pack(side=tk.LEFT, padx=2)
        self.line1_entry.insert(0, "0")
        self.line1_entry.bind('<Return>', lambda e: self.update_line_from_entry(1))
        self.line1_entry.bind('<FocusOut>', lambda e: self.update_line_from_entry(1))
        
        self.line1_slider = tk.Scale(
            left_col,
            from_=0,
            to=1000,
            orient=tk.HORIZONTAL,
            variable=self.analysis_line1_x,
            command=lambda v: self.update_line_from_slider(1),
            length=120
        )
        self.line1_slider.pack(fill=tk.X, padx=2, pady=2)
        
        # Line 2 controls
        line2_frame = tk.Frame(left_col)
        line2_frame.pack(fill=tk.X, pady=2)
        tk.Label(line2_frame, text="Line 2 X:").pack(side=tk.LEFT, padx=2)
        self.line2_entry = tk.Entry(line2_frame, width=6)
        self.line2_entry.pack(side=tk.LEFT, padx=2)
        self.line2_entry.insert(0, "0")
        self.line2_entry.bind('<Return>', lambda e: self.update_line_from_entry(2))
        self.line2_entry.bind('<FocusOut>', lambda e: self.update_line_from_entry(2))
        
        self.line2_slider = tk.Scale(
            left_col,
            from_=0,
            to=1000,
            orient=tk.HORIZONTAL,
            variable=self.analysis_line2_x,
            command=lambda v: self.update_line_from_slider(2),
            length=120
        )
        self.line2_slider.pack(fill=tk.X, padx=2, pady=2)
        
        # Right: Action Buttons
        actions_col = tk.LabelFrame(top_row, text="Actions", padx=5, pady=5)
        actions_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        
        # Detect centerline button
        detect_button = tk.Button(
            actions_col,
            text="Detect Centerline",
            command=self.segment_brown_line,
            bg="#4CAF50",
            fg="white",
            font=("Arial", 9, "bold"),
            padx=5,
            pady=3
        )
        detect_button.pack(fill=tk.X, pady=2)
        
        # Detect axis markers button
        detect_markers_button = tk.Button(
            actions_col,
            text="Detect Axis Markers",
            command=self.detect_axis_markers,
            bg="#FF9800",
            fg="white",
            font=("Arial", 9, "bold"),
            padx=5,
            pady=3
        )
        detect_markers_button.pack(fill=tk.X, pady=2)
        
        # Calculate areas button
        calculate_button = tk.Button(
            actions_col,
            text="Calculate Flow Areas",
            command=self.calculate_flow_areas,
            bg="#2196F3",
            fg="white",
            font=("Arial", 9, "bold"),
            padx=5,
            pady=3
        )
        calculate_button.pack(fill=tk.X, pady=2)
        
        # Bottom row: Velocity Calibration and Configuration side by side
        bottom_row = tk.Frame(right_panel)
        bottom_row.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left: Velocity Calibration
        velocity_col = tk.LabelFrame(bottom_row, text="Velocity Calibration", padx=5, pady=5)
        velocity_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        
        cms_frame = tk.Frame(velocity_col)
        cms_frame.pack(fill=tk.X, pady=2)
        tk.Label(cms_frame, text="cm/s between markers:").pack(side=tk.LEFT, padx=2)
        self.cms_entry = tk.Entry(cms_frame, width=8, textvariable=self.cms_between_markers)
        self.cms_entry.pack(side=tk.LEFT, padx=2)
        self.cms_entry.bind('<Return>', lambda e: self.update_velocity_calibration())
        self.cms_entry.bind('<FocusOut>', lambda e: self.update_velocity_calibration())
        
        # Right: Configuration Info panel
        info_col = tk.LabelFrame(bottom_row, text="Configuration", padx=5, pady=5)
        info_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        
        # Info panel
        info_frame = tk.Frame(info_col)
        info_frame.pack(fill=tk.BOTH, expand=True)
        
        self.info_text = tk.Text(info_frame, width=20, height=10, wrap=tk.WORD)
        self.info_text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar_info = tk.Scrollbar(info_frame, command=self.info_text.yview)
        scrollbar_info.pack(side=tk.RIGHT, fill=tk.Y)
        self.info_text.config(yscrollcommand=scrollbar_info.set)
        
        # Create bottom section with results table
        table_section = tk.Frame(main_frame)
        table_section.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=False, pady=(5, 0))
        table_section.config(height=200)  # Set initial height
        
        # Table frame with label and export button
        table_frame = tk.LabelFrame(table_section, text="Measurement Results", padx=5, pady=5)
        table_frame.pack(fill=tk.BOTH, expand=True)
        
        # Export button
        button_frame = tk.Frame(table_frame)
        button_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))
        export_button = tk.Button(
            button_frame,
            text="Export to CSV",
            command=self.export_to_csv,
            bg="#4CAF50",
            fg="white",
            font=("Arial", 9, "bold"),
            padx=10,
            pady=3
        )
        export_button.pack(side=tk.RIGHT, padx=5)
        
        # Create table (Treeview)
        table_container = tk.Frame(table_frame)
        table_container.pack(fill=tk.BOTH, expand=True)
        
        # Scrollbars for table
        table_v_scrollbar = tk.Scrollbar(table_container, orient=tk.VERTICAL)
        table_v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        table_h_scrollbar = tk.Scrollbar(table_container, orient=tk.HORIZONTAL)
        table_h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Treeview table
        columns = ("Image", "Line1_X", "Line2_X", "Area_Above", "Area_Below", "Total_Area",
                   "Area_Above_cm", "Area_Below_cm", "Total_Area_cm",
                   "Pos_Percent", "Neg_Percent", "Centerline_Y", "Timestamp")
        self.results_table = ttk.Treeview(table_container, columns=columns, show="headings",
                                          yscrollcommand=table_v_scrollbar.set,
                                          xscrollcommand=table_h_scrollbar.set)
        self.results_table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Configure scrollbars
        table_v_scrollbar.config(command=self.results_table.yview)
        table_h_scrollbar.config(command=self.results_table.xview)
        
        # Define column headings and widths
        column_configs = {
            "Image": ("Image Name", 150),
            "Line1_X": ("Line 1 X", 80),
            "Line2_X": ("Line 2 X", 80),
            "Area_Above": ("Area Above (px²)", 120),
            "Area_Below": ("Area Below (px²)", 120),
            "Total_Area": ("Total Area (px²)", 120),
            "Area_Above_cm": ("Area Above (cm)", 120),
            "Area_Below_cm": ("Area Below (cm)", 120),
            "Total_Area_cm": ("Total Area (cm)", 120),
            "Pos_Percent": ("Positive %", 90),
            "Neg_Percent": ("Negative %", 90),
            "Centerline_Y": ("Centerline Y", 100),
            "Timestamp": ("Timestamp", 150)
        }
        
        for col in columns:
            heading, width = column_configs[col]
            self.results_table.heading(col, text=heading)
            self.results_table.column(col, width=width, anchor=tk.CENTER)
        
        # Status bar
        self.status_bar = tk.Label(
            self.root, 
            text="Ready - Load a PNG file to begin", 
            bd=1, 
            relief=tk.SUNKEN, 
            anchor=tk.W
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def load_config(self):
        """Load configuration from YAML file."""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    self.config = yaml.safe_load(f) or {}
                self.update_status(f"Config loaded from {self.config_path}")
                
                # Load analysis line coordinates if available
                if 'analysis_lines' in self.config:
                    al = self.config['analysis_lines']
                    self.analysis_line1_x.set(al.get('line1_x', 0))
                    self.analysis_line2_x.set(al.get('line2_x', 0))
                    # Update entry fields
                    self.line1_entry.delete(0, tk.END)
                    self.line1_entry.insert(0, str(self.analysis_line1_x.get()))
                    self.line2_entry.delete(0, tk.END)
                    self.line2_entry.insert(0, str(self.analysis_line2_x.get()))
                
                # Update slider ranges based on bounding box
                self.update_slider_ranges()
                self.update_info_panel()
            else:
                self.config = {}
                self.update_status(f"Config file not found: {self.config_path}")
        except Exception as e:
            messagebox.showerror("Config Error", f"Failed to load config: {e}")
            self.config = {}
    
    def update_slider_ranges(self):
        """Update slider ranges based on bounding box or image size."""
        max_val = 1000  # Default
        
        if 'bounding_box' in self.config:
            bb = self.config['bounding_box']
            x_max = bb.get('x_max', 1000)
            max_val = max(max_val, x_max)
        elif self.current_image:
            max_val = self.current_image.size[0]
        
        self.line1_slider.config(to=max_val)
        self.line2_slider.config(to=max_val)
    
    def update_line_from_slider(self, line_num: int):
        """Update line coordinate from slider and refresh display."""
        if line_num == 1:
            val = self.analysis_line1_x.get()
            # Ensure line2 >= line1
            if val > self.analysis_line2_x.get():
                self.analysis_line2_x.set(val)
        else:
            val = self.analysis_line2_x.get()
            # Ensure line2 >= line1
            if val < self.analysis_line1_x.get():
                self.analysis_line1_x.set(val)
        
        # Update entry field
        if line_num == 1:
            self.line1_entry.delete(0, tk.END)
            self.line1_entry.insert(0, str(self.analysis_line1_x.get()))
        else:
            self.line2_entry.delete(0, tk.END)
            self.line2_entry.insert(0, str(self.analysis_line2_x.get()))
        
        self.refresh_image()
    
    def update_line_from_entry(self, line_num: int):
        """Update line coordinate from text entry and refresh display."""
        try:
            if line_num == 1:
                val = int(self.line1_entry.get())
                # Ensure line2 >= line1
                if val > self.analysis_line2_x.get():
                    self.analysis_line2_x.set(val)
                    self.line2_entry.delete(0, tk.END)
                    self.line2_entry.insert(0, str(val))
                self.analysis_line1_x.set(val)
                self.line1_slider.set(val)
            else:
                val = int(self.line2_entry.get())
                # Ensure line2 >= line1
                if val < self.analysis_line1_x.get():
                    self.analysis_line1_x.set(val)
                    self.line1_entry.delete(0, tk.END)
                    self.line1_entry.insert(0, str(val))
                    self.line1_slider.set(val)
                self.analysis_line2_x.set(val)
                self.line2_slider.set(val)
            
            self.refresh_image()
        except ValueError:
            # Invalid input, restore previous value
            if line_num == 1:
                self.line1_entry.delete(0, tk.END)
                self.line1_entry.insert(0, str(self.analysis_line1_x.get()))
            else:
                self.line2_entry.delete(0, tk.END)
                self.line2_entry.insert(0, str(self.analysis_line2_x.get()))
    
    def update_velocity_calibration(self):
        """Update velocity calibration when user changes cm/s value."""
        try:
            cms_value = float(self.cms_entry.get())
            if cms_value <= 0:
                raise ValueError("Value must be positive")
            self.cms_between_markers.set(str(cms_value))
            self.calculate_velocity_calibration()
            self.update_info_panel()
        except ValueError:
            # Invalid input, restore previous value
            self.cms_entry.delete(0, tk.END)
            self.cms_entry.insert(0, self.cms_between_markers.get())
    
    def calculate_area_conversion_factor(self):
        """
        Calculate conversion factor from px² to cm.
        Uses: X direction (pixels → seconds) and Y direction (pixels → cm/s)
        Result: px² → (seconds × cm/s) = cm
        Conversion factor = (cm_per_second_per_pixel / pixels_per_second)
        """
        if self.pixels_per_second is not None and self.cm_per_second_per_pixel is not None:
            if self.pixels_per_second > 0:
                return self.cm_per_second_per_pixel / self.pixels_per_second
        return None
    
    def calculate_velocity_calibration(self):
        """Calculate cm/s per pixel from velocity marker spacing."""
        if not self.velocity_markers_y or len(self.velocity_markers_y) < 2:
            self.cm_per_second_per_pixel = None
            return
        
        try:
            # Calculate distances between consecutive markers
            distances = []
            sorted_y = sorted(self.velocity_markers_y)
            for i in range(len(sorted_y) - 1):
                dist = sorted_y[i + 1] - sorted_y[i]
                if dist > 0:  # Only positive distances
                    distances.append(dist)
            
            if distances:
                # Get cm/s between markers from user input
                cms_between = float(self.cms_between_markers.get())
                
                # Calculate average distance
                avg_distance = np.mean(distances)
                
                # Calculate cm/s per pixel
                self.cm_per_second_per_pixel = cms_between / avg_distance
            else:
                self.cm_per_second_per_pixel = None
        except (ValueError, ZeroDivisionError):
            self.cm_per_second_per_pixel = None
    
    def update_info_panel(self):
        """Update the information panel with current configuration."""
        self.info_text.delete(1.0, tk.END)
        
        if not self.config:
            self.info_text.insert(tk.END, "No configuration loaded.\n")
            return
        
        self.info_text.insert(tk.END, "Bounding Boxes:\n")
        self.info_text.insert(tk.END, "=" * 20 + "\n\n")
        
        # Display bounding box
        if 'bounding_box' in self.config:
            bb = self.config['bounding_box']
            self.info_text.insert(tk.END, "Bounding Box:\n")
            self.info_text.insert(tk.END, f"  x_min: {bb.get('x_min', 'N/A')}\n")
            self.info_text.insert(tk.END, f"  y_min: {bb.get('y_min', 'N/A')}\n")
            self.info_text.insert(tk.END, f"  x_max: {bb.get('x_max', 'N/A')}\n")
            self.info_text.insert(tk.END, f"  y_max: {bb.get('y_max', 'N/A')}\n\n")
        
        # Display centerline box
        if 'centerline_box' in self.config:
            cb = self.config['centerline_box']
            self.info_text.insert(tk.END, "Centerline Box:\n")
            self.info_text.insert(tk.END, f"  x_min: {cb.get('x_min', 'N/A')}\n")
            self.info_text.insert(tk.END, f"  y_min: {cb.get('y_min', 'N/A')}\n")
            self.info_text.insert(tk.END, f"  x_max: {cb.get('x_max', 'N/A')}\n")
            self.info_text.insert(tk.END, f"  y_max: {cb.get('y_max', 'N/A')}\n\n")
        
        if self.current_image:
            self.info_text.insert(tk.END, f"\nImage: {self.current_image_path.name}\n")
            self.info_text.insert(tk.END, f"Size: {self.current_image.size[0]} x {self.current_image.size[1]}\n")
        
        # Display analysis lines info
        self.info_text.insert(tk.END, f"\nAnalysis Lines:\n")
        self.info_text.insert(tk.END, f"  Line 1 X: {self.analysis_line1_x.get()}\n")
        self.info_text.insert(tk.END, f"  Line 2 X: {self.analysis_line2_x.get()}\n")
        width = self.analysis_line2_x.get() - self.analysis_line1_x.get()
        self.info_text.insert(tk.END, f"  Width: {width} pixels\n")
        
        # Display centerline detection info
        if self.detected_line_segments:
            self.info_text.insert(tk.END, f"\nCenterline Detected:\n")
            self.info_text.insert(tk.END, f"  Segments: {len(self.detected_line_segments)}\n")
            total_points = sum(len(seg) for seg in self.detected_line_segments)
            self.info_text.insert(tk.END, f"  Points: {total_points}\n")
            if self.centerline_y is not None:
                self.info_text.insert(tk.END, f"  Y Position: {self.centerline_y:.1f}\n")
        
        # Display axis marker detection info
        if self.axis_marker_mask is not None:
            num_masked = np.sum(self.axis_marker_mask)
            self.info_text.insert(tk.END, f"\nAxis Markers:\n")
            self.info_text.insert(tk.END, f"  Masked pixels: {num_masked}\n")
            if len(self.taller_markers_x) > 0:
                self.info_text.insert(tk.END, f"  Taller markers: {len(self.taller_markers_x)}\n")
            if self.pixels_per_second is not None:
                self.info_text.insert(tk.END, f"  Pixels/second: {self.pixels_per_second:.2f}\n")
        
        # Display velocity marker detection info
        if self.velocity_marker_mask is not None:
            num_velocity = np.sum(self.velocity_marker_mask)
            self.info_text.insert(tk.END, f"\nVelocity Markers:\n")
            self.info_text.insert(tk.END, f"  Detected pixels: {num_velocity}\n")
            if len(self.velocity_markers_y) > 0:
                self.info_text.insert(tk.END, f"  Markers found: {len(self.velocity_markers_y)}\n")
                if len(self.velocity_markers_y) >= 2:
                    sorted_y = sorted(self.velocity_markers_y)
                    distances = [sorted_y[i + 1] - sorted_y[i] for i in range(len(sorted_y) - 1) if sorted_y[i + 1] - sorted_y[i] > 0]
                    if distances:
                        avg_distance = np.mean(distances)
                        self.info_text.insert(tk.END, f"  Avg spacing: {avg_distance:.1f} px\n")
            if self.cm_per_second_per_pixel is not None:
                self.info_text.insert(tk.END, f"  cm/s per pixel: {self.cm_per_second_per_pixel:.4f}\n")
        
        # Display area conversion info
        conversion_factor = self.calculate_area_conversion_factor()
        if conversion_factor is not None:
            self.info_text.insert(tk.END, f"\nArea Conversion:\n")
            self.info_text.insert(tk.END, f"  X: pixels → seconds ({self.pixels_per_second:.2f} px/s)\n")
            self.info_text.insert(tk.END, f"  Y: pixels → cm/s ({self.cm_per_second_per_pixel:.4f} cm/s per px)\n")
            self.info_text.insert(tk.END, f"  Conversion: {conversion_factor:.6f} cm per px²\n")
        
        # Display flow area calculations
        if self.area_above > 0 or self.area_below > 0:
            self.info_text.insert(tk.END, f"\nFlow Areas:\n")
            self.info_text.insert(tk.END, f"  Positive (above): {self.area_above} px²")
            if conversion_factor is not None:
                area_above_cm = self.area_above * conversion_factor
                self.info_text.insert(tk.END, f" ({area_above_cm:.4f} cm)")
            self.info_text.insert(tk.END, f"\n")
            
            self.info_text.insert(tk.END, f"  Negative (below): {self.area_below} px²")
            if conversion_factor is not None:
                area_below_cm = self.area_below * conversion_factor
                self.info_text.insert(tk.END, f" ({area_below_cm:.4f} cm)")
            self.info_text.insert(tk.END, f"\n")
            
            total_area = self.area_above + self.area_below
            if total_area > 0:
                pos_percent = (self.area_above / total_area) * 100
                neg_percent = (self.area_below / total_area) * 100
                self.info_text.insert(tk.END, f"  Positive: {pos_percent:.1f}%\n")
                self.info_text.insert(tk.END, f"  Negative: {neg_percent:.1f}%\n")
    
    def load_image(self):
        """Load a PNG image file."""
        file_path = filedialog.askopenfilename(
            title="Select PNG Image",
            filetypes=[("PNG files", "*.png"), ("All files", "*.*")]
        )
        
        if not file_path:
            return
        
        try:
            self.current_image_path = Path(file_path)
            self.current_image = Image.open(file_path)
            
            # Convert to RGB if necessary
            if self.current_image.mode != 'RGB':
                self.current_image = self.current_image.convert('RGB')
            
            # Update slider ranges based on image size
            self.update_slider_ranges()
            
            # Reset axis marker mask and time calibration when loading new image
            self.axis_marker_mask = None
            self.pixels_per_second = None
            self.taller_markers_x = []
            self.velocity_marker_mask = None
            self.velocity_markers_y = []
            self.cm_per_second_per_pixel = None
            
            self.display_image()
            self.update_status(f"Loaded: {self.current_image_path.name}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image: {e}")
            self.update_status(f"Error loading image: {e}")
    
    def display_image(self):
        """Display the current image on the canvas with bounding boxes."""
        if self.current_image is None:
            return
        
        # Create a copy of the image for drawing
        display_image = self.current_image.copy()
        
        # Draw bounding boxes on the image
        self.draw_boxes_on_image(display_image)
        
        # Convert to PhotoImage
        self.photo = ImageTk.PhotoImage(display_image)
        
        # Clear canvas and add image
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        
        # Update scroll region
        self.canvas.config(scrollregion=self.canvas.bbox("all"))
        
        # Update info panel
        self.update_info_panel()
    
    def draw_dotted_rectangle(self, draw, bbox, color, width=3, dash_length=5, gap_length=5):
        """
        Draw a dotted rectangle.
        
        Args:
            draw: ImageDraw object
            bbox: Tuple of ((x_min, y_min), (x_max, y_max))
            color: Color for the rectangle
            width: Line width
            dash_length: Length of each dash segment
            gap_length: Length of gap between dashes
        """
        (x_min, y_min), (x_max, y_max) = bbox
        
        # Draw top edge (left to right)
        x = x_min
        while x < x_max:
            dash_end = min(x + dash_length, x_max)
            draw.line([(x, y_min), (dash_end, y_min)], fill=color, width=width)
            x += dash_length + gap_length
        
        # Draw bottom edge (left to right)
        x = x_min
        while x < x_max:
            dash_end = min(x + dash_length, x_max)
            draw.line([(x, y_max), (dash_end, y_max)], fill=color, width=width)
            x += dash_length + gap_length
        
        # Draw left edge (top to bottom)
        y = y_min
        while y < y_max:
            dash_end = min(y + dash_length, y_max)
            draw.line([(x_min, y), (x_min, dash_end)], fill=color, width=width)
            y += dash_length + gap_length
        
        # Draw right edge (top to bottom)
        y = y_min
        while y < y_max:
            dash_end = min(y + dash_length, y_max)
            draw.line([(x_max, y), (x_max, dash_end)], fill=color, width=width)
            y += dash_length + gap_length
    
    def draw_boxes_on_image(self, image: Image.Image):
        """Draw bounding boxes on the image using PIL."""
        from PIL import ImageDraw
        
        draw = ImageDraw.Draw(image)
        
        # Draw bounding box
        if 'bounding_box' in self.config:
            bb = self.config['bounding_box']
            x_min = bb.get('x_min', 0)
            y_min = bb.get('y_min', 0)
            x_max = bb.get('x_max', 0)
            y_max = bb.get('y_max', 0)
            
            if x_min < x_max and y_min < y_max:
                # Draw dotted rectangle outline
                self.draw_dotted_rectangle(
                    draw,
                    ((x_min, y_min), (x_max, y_max)),
                    self.box_colors.get('bounding_box', 'red'),
                    width=3
                )
                # Add label
                draw.text(
                    (x_min, y_min - 15),
                    "Bounding Box",
                    fill=self.box_colors.get('bounding_box', 'red')
                )
        
        # Draw centerline box
        if 'centerline_box' in self.config:
            cb = self.config['centerline_box']
            x_min = cb.get('x_min', 0)
            y_min = cb.get('y_min', 0)
            x_max = cb.get('x_max', 0)
            y_max = cb.get('y_max', 0)
            
            if x_min < x_max and y_min < y_max:
                # Draw dotted rectangle outline
                self.draw_dotted_rectangle(
                    draw,
                    ((x_min, y_min), (x_max, y_max)),
                    self.box_colors.get('centerline_box', 'blue'),
                    width=3
                )
                # Add label
                draw.text(
                    (x_min, y_min - 15),
                    "Centerline Box",
                    fill=self.box_colors.get('centerline_box', 'blue')
                )
        
        # Draw detected line segments
        if self.detected_line_segments:
            for segment in self.detected_line_segments:
                if len(segment) > 1:
                    # Draw line connecting points in segment
                    for i in range(len(segment) - 1):
                        draw.line(
                            [segment[i], segment[i + 1]],
                            fill='lime',
                            width=2
                        )
                    # Draw points
                    for point in segment:
                        draw.ellipse(
                            [point[0] - 2, point[1] - 2, point[0] + 2, point[1] + 2],
                            fill='lime',
                            outline='darkgreen',
                            width=1
                        )
        
        # Draw vertical analysis lines (dashed, within bounding box)
        if 'bounding_box' in self.config:
            bb = self.config['bounding_box']
            y_min = bb.get('y_min', 0)
            y_max = bb.get('y_max', 0)
            x_min = bb.get('x_min', 0)
            x_max = bb.get('x_max', 0)
            
            if y_min < y_max and x_min < x_max:
                line1_x = self.analysis_line1_x.get()
                line2_x = self.analysis_line2_x.get()
                
                # Ensure lines are within bounding box x range
                line1_x = max(x_min, min(line1_x, x_max))
                line2_x = max(x_min, min(line2_x, x_max))
                
                # Draw dashed vertical lines
                dash_pattern = [5, 5]  # 5 pixels on, 5 pixels off
                
                # Line 1
                if x_min <= line1_x <= x_max:
                    y = y_min
                    while y < y_max:
                        # Draw dash segment
                        dash_end = min(y + dash_pattern[0], y_max)
                        draw.line(
                            [(line1_x, y), (line1_x, dash_end)],
                            fill=self.analysis_line_color,
                            width=2
                        )
                        y += sum(dash_pattern)
                
                # Line 2
                if x_min <= line2_x <= x_max:
                    y = y_min
                    while y < y_max:
                        # Draw dash segment
                        dash_end = min(y + dash_pattern[0], y_max)
                        draw.line(
                            [(line2_x, y), (line2_x, dash_end)],
                            fill=self.analysis_line_color,
                            width=2
                        )
                        y += sum(dash_pattern)
        
        # Draw detected axis markers
        if self.axis_marker_mask is not None and 'bounding_box' in self.config:
            bb = self.config['bounding_box']
            bb_x_min = bb.get('x_min', 0)
            bb_y_min = bb.get('y_min', 0)
            
            # Create overlay for highlighting markers
            overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            
            # Find connected regions in the mask for efficient drawing
            try:
                from scipy import ndimage
                # Label connected components
                labeled, num_features = ndimage.label(self.axis_marker_mask)
                
                marker_color = (255, 165, 0, 128)  # Orange with 50% transparency
                outline_color = (255, 140, 0, 200)  # Slightly darker orange outline
                
                for i in range(1, num_features + 1):
                    component = labeled == i
                    y_coords, x_coords = np.where(component)
                    
                    if len(y_coords) > 0:
                        # Get bounding box of this component
                        y_min_comp = np.min(y_coords)
                        y_max_comp = np.max(y_coords)
                        x_min_comp = np.min(x_coords)
                        x_max_comp = np.max(x_coords)
                        
                        # Convert to global coordinates
                        global_x_min = bb_x_min + x_min_comp
                        global_y_min = bb_y_min + y_min_comp
                        global_x_max = bb_x_min + x_max_comp
                        global_y_max = bb_y_min + y_max_comp
                        
                        # Draw rectangle outline for this marker region
                        overlay_draw.rectangle(
                            [(global_x_min, global_y_min), (global_x_max, global_y_max)],
                            fill=marker_color,
                            outline=outline_color,
                            width=2
                        )
                
            except ImportError:
                # Fallback: draw individual pixels if scipy not available
                mask_y_coords, mask_x_coords = np.where(self.axis_marker_mask)
                
                if len(mask_y_coords) > 0:
                    marker_color = (255, 165, 0, 128)  # Orange with 50% transparency
                    outline_color = (255, 140, 0, 200)
                    
                    # Draw every 5th pixel to avoid performance issues
                    step = max(1, len(mask_y_coords) // 1000)  # Limit to ~1000 draws
                    for i in range(0, len(mask_y_coords), step):
                        global_x = bb_x_min + mask_x_coords[i]
                        global_y = bb_y_min + mask_y_coords[i]
                        
                        # Draw a small rectangle
                        overlay_draw.rectangle(
                            [(global_x - 2, global_y - 2), (global_x + 2, global_y + 2)],
                            fill=marker_color,
                            outline=outline_color,
                            width=1
                        )
            
            # Composite the overlay onto the image
            image.paste(overlay, (0, 0), overlay)
        
        # Draw detected velocity markers (in orange)
        if self.velocity_marker_mask is not None and 'bounding_box' in self.config:
            bb = self.config['bounding_box']
            bb_x_min = bb.get('x_min', 0)
            bb_y_min = bb.get('y_min', 0)
            
            # Create overlay for highlighting velocity markers
            overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            
            # Find connected regions in the velocity marker mask
            try:
                from scipy import ndimage
                # Label connected components
                labeled, num_features = ndimage.label(self.velocity_marker_mask)
                
                velocity_color = (255, 165, 0, 128)  # Orange with 50% transparency
                outline_color = (200, 120, 0, 200)  # Darker orange outline
                
                for i in range(1, num_features + 1):
                    component = labeled == i
                    y_coords, x_coords = np.where(component)
                    
                    if len(y_coords) > 0:
                        # Get bounding box of this component
                        y_min_comp = np.min(y_coords)
                        y_max_comp = np.max(y_coords)
                        x_min_comp = np.min(x_coords)
                        x_max_comp = np.max(x_coords)
                        
                        # Convert to global coordinates
                        global_x_min = bb_x_min + x_min_comp
                        global_y_min = bb_y_min + y_min_comp
                        global_x_max = bb_x_min + x_max_comp
                        global_y_max = bb_y_min + y_max_comp
                        
                        # Draw rectangle outline for this velocity marker region
                        overlay_draw.rectangle(
                            [(global_x_min, global_y_min), (global_x_max, global_y_max)],
                            fill=velocity_color,
                            outline=outline_color,
                            width=2
                        )
                
            except ImportError:
                # Fallback: draw individual pixels if scipy not available
                mask_y_coords, mask_x_coords = np.where(self.velocity_marker_mask)
                
                if len(mask_y_coords) > 0:
                    velocity_color = (255, 165, 0, 128)  # Orange with 50% transparency
                    outline_color = (200, 120, 0, 200)  # Darker orange outline
                    
                    # Draw every pixel (velocity markers are small)
                    for i in range(len(mask_y_coords)):
                        global_x = bb_x_min + mask_x_coords[i]
                        global_y = bb_y_min + mask_y_coords[i]
                        
                        # Draw a small rectangle
                        overlay_draw.rectangle(
                            [(global_x - 1, global_y - 1), (global_x + 1, global_y + 1)],
                            fill=velocity_color,
                            outline=outline_color,
                            width=1
                        )
            
            # Composite the overlay onto the image
            image.paste(overlay, (0, 0), overlay)
        
        # Draw highlighted segmented areas above and below centerline
        if self.above_mask is not None and self.below_mask is not None and self.analysis_region_coords is not None:
            x_min_reg, y_min_reg, x_max_reg, y_max_reg = self.analysis_region_coords
            
            # Create overlay for highlighting areas
            overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
            overlay_array = np.array(overlay)
            
            # Two shades of light blue
            # Lighter blue for area above (positive flow)
            light_blue_above = np.array([173, 216, 230, 120], dtype=np.uint8)  # Light blue with ~47% transparency
            # Slightly darker blue for area below (negative flow)
            light_blue_below = np.array([135, 206, 250, 120], dtype=np.uint8)  # Sky blue with ~47% transparency
            
            # Draw above mask (area above centerline)
            above_y_coords, above_x_coords = np.where(self.above_mask)
            if len(above_y_coords) > 0:
                # Convert local coordinates to global coordinates
                global_y_coords = y_min_reg + above_y_coords
                global_x_coords = x_min_reg + above_x_coords
                
                # Ensure coordinates are within image bounds
                valid_mask = ((global_y_coords >= 0) & (global_y_coords < overlay_array.shape[0]) &
                             (global_x_coords >= 0) & (global_x_coords < overlay_array.shape[1]))
                global_y_coords = global_y_coords[valid_mask]
                global_x_coords = global_x_coords[valid_mask]
                
                # Set pixels in overlay
                overlay_array[global_y_coords, global_x_coords] = light_blue_above
            
            # Draw below mask (area below centerline)
            below_y_coords, below_x_coords = np.where(self.below_mask)
            if len(below_y_coords) > 0:
                # Convert local coordinates to global coordinates
                global_y_coords = y_min_reg + below_y_coords
                global_x_coords = x_min_reg + below_x_coords
                
                # Ensure coordinates are within image bounds
                valid_mask = ((global_y_coords >= 0) & (global_y_coords < overlay_array.shape[0]) &
                             (global_x_coords >= 0) & (global_x_coords < overlay_array.shape[1]))
                global_y_coords = global_y_coords[valid_mask]
                global_x_coords = global_x_coords[valid_mask]
                
                # Set pixels in overlay
                overlay_array[global_y_coords, global_x_coords] = light_blue_below
            
            # Convert back to PIL Image and composite
            overlay = Image.fromarray(overlay_array)
            image.paste(overlay, (0, 0), overlay)
    
    def refresh_image(self):
        """Refresh the current image display."""
        if self.current_image is None:
            messagebox.showinfo("Info", "No image loaded. Please load an image first.")
            return
        
        self.display_image()
        self.update_status("Image refreshed")
    
    def segment_brown_line(self):
        """Detect and segment the brown line within the centerline_box."""
        if self.current_image is None:
            messagebox.showinfo("Info", "Please load an image first.")
            return
        
        if 'centerline_box' not in self.config:
            messagebox.showwarning("Warning", "Centerline box not defined in config.")
            return
        
        try:
            cb = self.config['centerline_box']
            x_min = cb.get('x_min', 0)
            y_min = cb.get('y_min', 0)
            x_max = cb.get('x_max', 0)
            y_max = cb.get('y_max', 0)
            
            if x_min >= x_max or y_min >= y_max:
                messagebox.showwarning("Warning", "Invalid centerline box coordinates.")
                return
            
            # Extract the centerline box region
            img_array = np.array(self.current_image)
            region = img_array[y_min:y_max, x_min:x_max]
            
            # Convert brown color to numpy array
            brown_rgb = np.array(self.brown_line_color)
            
            # Find pixels matching brown color (with tolerance)
            # Calculate color distance for each pixel
            color_diff = np.abs(region.astype(np.int16) - brown_rgb)
            color_distance = np.sqrt(np.sum(color_diff ** 2, axis=2))
            brown_mask = color_distance <= self.brown_line_tolerance
            
            # Find line segments
            # Since the line spans the full width, we'll look for the y-coordinate
            # of brown pixels at each x position
            self.detected_line_segments = []
            
            # For each x position in the region, find y positions with brown pixels
            line_points_by_x = {}
            for local_x in range(region.shape[1]):
                y_positions = np.where(brown_mask[:, local_x])[0]
                if len(y_positions) > 0:
                    # Use median y position for this x (in case of multiple matches)
                    y_pos = int(np.median(y_positions))
                    # Convert to global coordinates
                    global_x = x_min + local_x
                    global_y = y_min + y_pos
                    line_points_by_x[global_x] = global_y
            
            # Group continuous segments (handle gaps)
            if line_points_by_x:
                sorted_x = sorted(line_points_by_x.keys())
                current_segment = []
                
                for i, x in enumerate(sorted_x):
                    y = line_points_by_x[x]
                    
                    if not current_segment:
                        current_segment.append((x, y))
                    else:
                        # Check if there's a gap (more than 5 pixels)
                        prev_x = current_segment[-1][0]
                        if x - prev_x <= 5:
                            current_segment.append((x, y))
                        else:
                            # Gap detected, save current segment and start new one
                            if len(current_segment) > 1:
                                self.detected_line_segments.append(current_segment)
                            current_segment = [(x, y)]
                
                # Add last segment
                if len(current_segment) > 1:
                    self.detected_line_segments.append(current_segment)
            
            # Refresh display
            self.display_image()
            
            num_segments = len(self.detected_line_segments)
            if num_segments > 0:
                total_points = sum(len(seg) for seg in self.detected_line_segments)
                self.update_status(
                    f"Centerline detected: {num_segments} segment(s), {total_points} points"
                )
            else:
                self.update_status("No centerline detected")
                messagebox.showinfo(
                    "No Line Found",
                    "No brown line detected. Try adjusting the color tolerance."
                )
            
            self.update_info_panel()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to detect centerline: {e}")
            self.update_status(f"Error: {e}")
    
    def detect_axis_markers(self):
        """Detect rectangular axis markers within the bounding box and create a mask."""
        if self.current_image is None:
            messagebox.showinfo("Info", "Please load an image first.")
            return
        
        if 'bounding_box' not in self.config:
            messagebox.showwarning("Warning", "Bounding box not defined in config.")
            return
        
        try:
            # Get bounding box coordinates
            bb = self.config['bounding_box']
            x_min = bb.get('x_min', 0)
            y_min = bb.get('y_min', 0)
            x_max = bb.get('x_max', 0)
            y_max = bb.get('y_max', 0)
            
            if x_min >= x_max or y_min >= y_max:
                messagebox.showwarning("Warning", "Invalid bounding box coordinates.")
                return
            
            # Extract bounding box region
            img_array = np.array(self.current_image)
            bb_region = img_array[y_min:y_max, x_min:x_max]
            
            # Convert to grayscale for processing
            if len(bb_region.shape) == 3:
                # For RGB, check if any channel is very bright (white)
                # Markers are pure white or very close to white
                gray = np.mean(bb_region, axis=2).astype(np.uint8)
                # Also check individual channels for pure white detection
                max_channel = np.max(bb_region, axis=2)
            else:
                gray = bb_region.astype(np.uint8)
                max_channel = gray
            
            # Create binary mask: detect white/very bright pixels
            # Markers are pure white (255) or very close to white (>240)
            white_threshold = 240  # Pixels brighter than this are potential markers
            binary = max_channel > white_threshold
            
            # Try to detect rectangular shapes using contour detection
            # First, try with OpenCV if available
            try:
                import cv2
                use_opencv = True
            except ImportError:
                use_opencv = False
            
            if use_opencv:
                # Use OpenCV for better contour detection
                binary_uint8 = (binary * 255).astype(np.uint8)
                
                # Find contours
                contours, _ = cv2.findContours(binary_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                # Create mask for rectangular markers
                marker_mask = np.zeros(binary.shape, dtype=bool)
                self.taller_markers_x = []  # Reset taller markers list
                
                # Markers are 2x6 (12 pixels) and 2x12 (24 pixels)
                # Taller markers (2x12) represent 1 second intervals
                min_area = 8  # Minimum area (smaller than smallest marker to catch partial detections)
                max_area = 50  # Maximum area (larger than largest marker to account for slight variations)
                
                for contour in contours:
                    area = cv2.contourArea(contour)
                    
                    # Filter by area
                    if min_area <= area <= max_area:
                        # Get bounding rectangle
                        x, y, w, h = cv2.boundingRect(contour)
                        
                        # Check if it's a taller marker (2x12) - height 10-14 pixels
                        # Also check that it's below the centerline (x markers are never above centerline)
                        is_taller = False
                        if ((1 <= w <= 3 and 10 <= h <= 14) or  # Vertical taller marker (2x12)
                            (10 <= w <= 14 and 1 <= h <= 3)):   # Horizontal taller marker (12x2)
                            # Check if marker is below centerline
                            marker_y_center = y + h // 2
                            local_marker_y = marker_y_center  # Already in local coordinates
                            if self.centerline_y is not None:
                                local_centerline_y = self.centerline_y - y_min
                                # Only include if marker is below centerline
                                if local_marker_y > local_centerline_y:
                                    is_taller = True
                                    # Store X position of taller marker (use center X)
                                    global_x = x_min + x + w // 2
                                    self.taller_markers_x.append(global_x)
                            else:
                                # If centerline not detected yet, include all taller markers
                                # They will be filtered later
                                is_taller = True
                                global_x = x_min + x + w // 2
                                self.taller_markers_x.append(global_x)
                        
                        # Check if dimensions match expected marker sizes (2x6 or 2x12, with some tolerance)
                        # Allow for slight variations: width 1-3, height 4-14
                        if ((1 <= w <= 3 and 4 <= h <= 14) or  # Vertical markers (2x6 or 2x12)
                            (4 <= w <= 14 and 1 <= h <= 3)):    # Horizontal markers (6x2 or 12x2)
                            # Fill the rectangle in the mask
                            marker_mask[y:y+h, x:x+w] = True
                        # Also check aspect ratio for other rectangular markers
                        elif w > 0 and h > 0:
                            aspect_ratio = max(w, h) / max(min(w, h), 1)
                            # Allow elongated rectangles (markers can be 2x6 or 2x12)
                            if 2 <= aspect_ratio <= 7 and area >= 8 and area <= 50:
                                marker_mask[y:y+h, x:x+w] = True
                                # Check if it might be a taller marker based on area
                                if 20 <= area <= 30:  # Taller markers have ~24 pixels
                                    if not is_taller:
                                        # Check if marker is below centerline
                                        marker_y_center = y + h // 2
                                        if self.centerline_y is not None:
                                            local_centerline_y = self.centerline_y - y_min
                                            if marker_y_center > local_centerline_y:
                                                global_x = x_min + x + w // 2
                                                self.taller_markers_x.append(global_x)
                                        else:
                                            # If centerline not detected, include it
                                            global_x = x_min + x + w // 2
                                            self.taller_markers_x.append(global_x)
                
                # Sort taller markers by X position
                self.taller_markers_x.sort()
                
                # Calculate pixels per second from taller marker spacing
                if len(self.taller_markers_x) >= 2:
                    # Calculate distances between consecutive taller markers
                    distances = []
                    for i in range(len(self.taller_markers_x) - 1):
                        dist = self.taller_markers_x[i + 1] - self.taller_markers_x[i]
                        if dist > 0:  # Only positive distances
                            distances.append(dist)
                    
                    if distances:
                        # Use average distance (in case of slight variations)
                        avg_distance = np.mean(distances)
                        # Taller markers are 1 second apart
                        self.pixels_per_second = avg_distance
                
                self.axis_marker_mask = marker_mask
                
            else:
                # Fallback: Use morphological operations to detect rectangular regions
                from scipy import ndimage
                try:
                    # Use scipy for morphological operations
                    # Detect rectangular regions by finding connected components
                    labeled, num_features = ndimage.label(binary)
                    
                    marker_mask = np.zeros(binary.shape, dtype=bool)
                    self.taller_markers_x = []  # Reset taller markers list
                    
                    for i in range(1, num_features + 1):
                        component = labeled == i
                        y_coords, x_coords = np.where(component)
                        
                        if len(y_coords) > 0:
                            y_min_comp = np.min(y_coords)
                            y_max_comp = np.max(y_coords)
                            x_min_comp = np.min(x_coords)
                            x_max_comp = np.max(x_coords)
                            
                            # Check if it's roughly rectangular
                            comp_area = np.sum(component)
                            w = x_max_comp - x_min_comp + 1
                            h = y_max_comp - y_min_comp + 1
                            bbox_area = w * h
                            
                            # Rectangular markers should fill most of their bounding box
                            fill_ratio = comp_area / max(bbox_area, 1)
                            
                            # Markers are 2x6 (12 pixels) and 2x12 (24 pixels)
                            min_area = 8
                            max_area = 50
                            
                            # Check if it's a taller marker (2x12)
                            # Also check that it's below the centerline (x markers are never above centerline)
                            is_taller = False
                            if (min_area <= comp_area <= max_area and 
                                fill_ratio > 0.5 and
                                ((1 <= w <= 3 and 10 <= h <= 14) or  # Vertical taller marker
                                 (10 <= w <= 14 and 1 <= h <= 3))):   # Horizontal taller marker
                                # Check if marker is below centerline
                                marker_y_center = y_min_comp + h // 2
                                if self.centerline_y is not None:
                                    local_centerline_y = self.centerline_y - y_min
                                    # Only include if marker is below centerline
                                    if marker_y_center > local_centerline_y:
                                        is_taller = True
                                        global_x = x_min + x_min_comp + w // 2
                                        self.taller_markers_x.append(global_x)
                                else:
                                    # If centerline not detected yet, include all taller markers
                                    is_taller = True
                                    global_x = x_min + x_min_comp + w // 2
                                    self.taller_markers_x.append(global_x)
                            
                            # Check dimensions match expected marker sizes
                            if (min_area <= comp_area <= max_area and 
                                fill_ratio > 0.5 and  # At least 50% filled
                                ((1 <= w <= 3 and 4 <= h <= 14) or  # Vertical markers
                                 (4 <= w <= 14 and 1 <= h <= 3))):   # Horizontal markers
                                marker_mask[component] = True
                                # Also check by area for taller markers
                                if 20 <= comp_area <= 30 and not is_taller:
                                    # Check if marker is below centerline
                                    marker_y_center = y_min_comp + h // 2
                                    if self.centerline_y is not None:
                                        local_centerline_y = self.centerline_y - y_min
                                        if marker_y_center > local_centerline_y:
                                            global_x = x_min + x_min_comp + w // 2
                                            self.taller_markers_x.append(global_x)
                                    else:
                                        # If centerline not detected, include it
                                        global_x = x_min + x_min_comp + w // 2
                                        self.taller_markers_x.append(global_x)
                    
                    # Sort taller markers by X position
                    self.taller_markers_x.sort()
                    
                    # Calculate pixels per second from taller marker spacing
                    if len(self.taller_markers_x) >= 2:
                        distances = []
                        for i in range(len(self.taller_markers_x) - 1):
                            dist = self.taller_markers_x[i + 1] - self.taller_markers_x[i]
                            if dist > 0:
                                distances.append(dist)
                        if distances:
                            avg_distance = np.mean(distances)
                            self.pixels_per_second = avg_distance
                    
                    self.axis_marker_mask = marker_mask
                    
                except ImportError:
                    # Simple fallback: detect small bright rectangular regions
                    # Look for 2x6 and 2x12 pixel regions
                    marker_mask = np.zeros(binary.shape, dtype=bool)
                    self.taller_markers_x = []  # Reset taller markers list
                    
                    # Scan for small rectangular white regions
                    for y in range(binary.shape[0] - 1):
                        for x in range(binary.shape[1] - 1):
                            if binary[y, x]:  # If pixel is white
                                # Check for 2x6 or 2x12 patterns
                                # Try vertical pattern (2 wide)
                                if (x + 1 < binary.shape[1] and 
                                    binary[y, x+1] and
                                    y + 5 < binary.shape[0]):
                                    # Check for 2x12 (taller marker)
                                    if y + 11 < binary.shape[0] and np.all(binary[y:y+12, x:x+2]):
                                        # Check if marker is below centerline
                                        marker_y_center = y + 6
                                        if self.centerline_y is not None:
                                            local_centerline_y = self.centerline_y - y_min
                                            if marker_y_center > local_centerline_y:
                                                marker_mask[y:y+12, x:x+2] = True
                                                global_x = x_min + x + 1  # Center X
                                                self.taller_markers_x.append(global_x)
                                        else:
                                            # If centerline not detected, include it
                                            marker_mask[y:y+12, x:x+2] = True
                                            global_x = x_min + x + 1  # Center X
                                            self.taller_markers_x.append(global_x)
                                    # Check for 2x6
                                    elif np.all(binary[y:y+6, x:x+2]):
                                        marker_mask[y:y+6, x:x+2] = True
                                # Try horizontal pattern (2 tall)
                                elif (y + 1 < binary.shape[0] and 
                                      binary[y+1, x] and
                                      x + 5 < binary.shape[1]):
                                    # Check for 12x2 (taller marker)
                                    if x + 11 < binary.shape[1] and np.all(binary[y:y+2, x:x+12]):
                                        # Check if marker is below centerline
                                        marker_y_center = y + 1
                                        if self.centerline_y is not None:
                                            local_centerline_y = self.centerline_y - y_min
                                            if marker_y_center > local_centerline_y:
                                                marker_mask[y:y+2, x:x+12] = True
                                                global_x = x_min + x + 6  # Center X
                                                self.taller_markers_x.append(global_x)
                                        else:
                                            # If centerline not detected, include it
                                            marker_mask[y:y+2, x:x+12] = True
                                            global_x = x_min + x + 6  # Center X
                                            self.taller_markers_x.append(global_x)
                                    # Check for 6x2
                                    elif np.all(binary[y:y+2, x:x+6]):
                                        marker_mask[y:y+2, x:x+6] = True
                    
                    # Sort taller markers by X position
                    self.taller_markers_x.sort()
                    
                    # Calculate pixels per second from taller marker spacing
                    if len(self.taller_markers_x) >= 2:
                        distances = []
                        for i in range(len(self.taller_markers_x) - 1):
                            dist = self.taller_markers_x[i + 1] - self.taller_markers_x[i]
                            if dist > 0:
                                distances.append(dist)
                        if distances:
                            avg_distance = np.mean(distances)
                            self.pixels_per_second = avg_distance
                    
                    self.axis_marker_mask = marker_mask
            
            # Filter out markers above centerline and within ±70 pixels of centerline
            if self.axis_marker_mask is not None:
                # Check if centerline is detected, if not warn user
                if self.centerline_y is None:
                    # Try to calculate centerline from detected segments if available
                    if self.detected_line_segments:
                        all_y_values = []
                        for segment in self.detected_line_segments:
                            for point in segment:
                                all_y_values.append(point[1])
                        if all_y_values:
                            self.centerline_y = np.mean(all_y_values)
                
                if self.centerline_y is not None:
                    # Count how many will be removed
                    original_count = np.sum(self.axis_marker_mask)
                    
                    # Create a filtered mask
                    filtered_mask = self.axis_marker_mask.copy()
                    
                    # Get all centerline Y positions for more accurate filtering
                    # If we have detected line segments, use them for more precise filtering
                    if self.detected_line_segments:
                        # Create a map of centerline Y positions by X coordinate
                        centerline_y_by_x = {}
                        for segment in self.detected_line_segments:
                            for x, y in segment:
                                # Convert to local coordinates
                                local_x = x - x_min
                                local_y = y - y_min
                                if 0 <= local_x < filtered_mask.shape[1]:
                                    if local_x not in centerline_y_by_x:
                                        centerline_y_by_x[local_x] = []
                                    centerline_y_by_x[local_x].append(local_y)
                        
                        # For each X position, get the average centerline Y
                        for local_x in centerline_y_by_x:
                            centerline_y_at_x = np.mean(centerline_y_by_x[local_x])
                            
                            # Remove markers above centerline (x markers are never above centerline)
                            if centerline_y_at_x > 0:
                                filtered_mask[0:int(centerline_y_at_x), local_x] = False
                            
                            # Exclude markers within ±70 pixels of centerline at this X position
                            exclusion_y_min = max(0, int(centerline_y_at_x - 70))
                            exclusion_y_max = min(filtered_mask.shape[0], int(centerline_y_at_x + 70))
                            if exclusion_y_min < exclusion_y_max:
                                filtered_mask[exclusion_y_min:exclusion_y_max, local_x] = False
                    else:
                        # Fallback: use average centerline Y position
                        local_centerline_y = self.centerline_y - y_min
                        
                        # Remove markers above centerline (x markers are never above centerline)
                        if local_centerline_y > 0:
                            filtered_mask[0:int(local_centerline_y), :] = False
                        
                        # Exclude markers within ±70 pixels of centerline
                        exclusion_y_min = max(0, int(local_centerline_y - 70))
                        exclusion_y_max = min(filtered_mask.shape[0], int(local_centerline_y + 70))
                        if exclusion_y_min < exclusion_y_max:
                            filtered_mask[exclusion_y_min:exclusion_y_max, :] = False
                    
                    self.axis_marker_mask = filtered_mask
                    
                    # Count how many were removed
                    removed_count = original_count - np.sum(self.axis_marker_mask)
                    if removed_count > 0:
                        print(f"Removed {removed_count} marker pixels (above centerline and within ±70 pixels)")
                else:
                    # Warn user that centerline needs to be detected
                    messagebox.showwarning(
                        "Centerline Not Detected",
                        "Centerline not detected. Please detect the centerline first for better marker filtering.\n"
                        "Some markers near the centerline may be incorrectly detected."
                    )
            
            # Convert to global coordinates mask
            if self.axis_marker_mask is not None:
                num_masked = np.sum(self.axis_marker_mask)
                
                # Check if centerline exclusion was applied
                exclusion_note = ""
                if self.centerline_y is not None:
                    exclusion_note = f"\nMarkers within ±70 pixels of centerline were excluded."
                
                # Add pixels per second info
                pps_note = ""
                if self.pixels_per_second is not None:
                    pps_note = f" | {self.pixels_per_second:.2f} px/s"
                
                self.update_status(f"Axis markers detected: {num_masked} pixels masked{pps_note}{exclusion_note}")
                
                # Refresh display to show highlighted markers
                self.display_image()
                self.update_info_panel()
                
                messagebox.showinfo(
                    "Markers Detected",
                    f"Detected axis markers: {num_masked} pixels will be excluded from calculations.\n"
                    f"Markers are highlighted in orange on the image.{exclusion_note}"
                )
            else:
                self.update_status("No axis markers detected")
                # Refresh display even if no markers found
                self.display_image()
                messagebox.showinfo("No Markers", "No axis markers detected. All pixels will be included.")
            
            # Detect velocity markers on the right edge of bounding box
            self.detect_velocity_markers(bb, x_min, y_min, x_max, y_max, img_array)
            
            # Refresh display to show velocity markers if detected
            if self.velocity_marker_mask is not None:
                num_velocity = np.sum(self.velocity_marker_mask)
                if num_velocity > 0:
                    # Refresh display and info panel
                    self.display_image()
                    self.update_info_panel()
                    self.update_status(f"Velocity markers detected: {num_velocity} pixels (highlighted in orange)")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to detect axis markers: {e}")
            self.update_status(f"Error: {e}")
            import traceback
            traceback.print_exc()
    
    def detect_velocity_markers(self, bb, x_min, y_min, x_max, y_max, img_array):
        """Detect vertical velocity markers on the right edge of the bounding box."""
        try:
            # Extract region near right edge (±5 pixels from right edge)
            right_edge_x = x_max - 1  # Right edge is at x_max - 1 (0-indexed)
            edge_region_x_min = max(x_min, right_edge_x - 5)
            edge_region_x_max = min(img_array.shape[1], right_edge_x + 6)  # Include right edge
            
            if edge_region_x_min >= edge_region_x_max:
                self.velocity_marker_mask = None
                return
            
            # Extract the edge region (within bounding box)
            edge_region = img_array[y_min:y_max, edge_region_x_min:edge_region_x_max]
            
            if edge_region.size == 0:
                self.velocity_marker_mask = None
                return
            
            # Convert to grayscale
            if len(edge_region.shape) == 3:
                max_channel = np.max(edge_region, axis=2)
            else:
                max_channel = edge_region.astype(np.uint8)
            
            # Detect white/very bright pixels
            white_threshold = 240
            binary = max_channel > white_threshold
            
            # Create mask for velocity markers (in bounding box coordinates)
            velocity_mask = np.zeros((y_max - y_min, x_max - x_min), dtype=bool)
            self.velocity_markers_y = []  # Reset Y positions list
            
            # Look for 2x6 and 2x12 pixel markers (2 rows, 6 or 12 columns)
            # These are horizontal markers (2 tall, 6 or 12 wide)
            for y in range(binary.shape[0] - 1):
                for x in range(binary.shape[1] - 1):
                    if binary[y, x] and binary[y + 1, x]:  # Check for 2 rows
                        # Check for 2x6 marker (2 rows, 6 columns)
                        if x + 5 < binary.shape[1]:
                            if np.all(binary[y:y+2, x:x+6]):
                                # Convert to bounding box local coordinates
                                # x in edge_region corresponds to edge_region_x_min + x in global
                                global_x = edge_region_x_min + x
                                local_x = global_x - x_min  # Convert to bounding box local
                                local_y = y
                                if 0 <= local_x < velocity_mask.shape[1] and 0 <= local_y < velocity_mask.shape[0]:
                                    # Make sure we don't go out of bounds
                                    x_end = min(local_x + 6, velocity_mask.shape[1])
                                    velocity_mask[local_y:local_y+2, local_x:x_end] = True
                                    # Store Y position (center of marker) in global coordinates
                                    global_y = y_min + local_y + 1  # Center Y of marker
                                    if global_y not in self.velocity_markers_y:
                                        self.velocity_markers_y.append(global_y)
                        
                        # Check for 2x12 marker (2 rows, 12 columns)
                        if x + 11 < binary.shape[1]:
                            if np.all(binary[y:y+2, x:x+12]):
                                # Convert to bounding box local coordinates
                                global_x = edge_region_x_min + x
                                local_x = global_x - x_min
                                local_y = y
                                if 0 <= local_x < velocity_mask.shape[1] and 0 <= local_y < velocity_mask.shape[0]:
                                    # Make sure we don't go out of bounds
                                    x_end = min(local_x + 12, velocity_mask.shape[1])
                                    velocity_mask[local_y:local_y+2, local_x:x_end] = True
                                    # Store Y position (center of marker) in global coordinates
                                    global_y = y_min + local_y + 1  # Center Y of marker
                                    if global_y not in self.velocity_markers_y:
                                        self.velocity_markers_y.append(global_y)
            
            # Only keep markers that are actually near the right edge
            # Filter to only markers within ±5 pixels of right edge in bounding box coordinates
            bb_width = x_max - x_min
            right_edge_local = bb_width - 1
            edge_min = max(0, right_edge_local - 5)
            edge_max = min(velocity_mask.shape[1], right_edge_local + 6)
            
            # Create filtered mask - only keep markers in the edge region
            filtered_velocity_mask = np.zeros_like(velocity_mask)
            if edge_min < edge_max:
                filtered_velocity_mask[:, edge_min:edge_max] = velocity_mask[:, edge_min:edge_max]
            
            self.velocity_marker_mask = filtered_velocity_mask
            
            num_velocity_markers = np.sum(self.velocity_marker_mask)
            if num_velocity_markers > 0:
                print(f"Detected {num_velocity_markers} velocity marker pixels")
                print(f"Found {len(self.velocity_markers_y)} velocity markers at Y positions: {sorted(self.velocity_markers_y)}")
                # Calculate velocity calibration
                self.calculate_velocity_calibration()
            else:
                print(f"No velocity markers detected in edge region ({edge_region_x_min} to {edge_region_x_max})")
                self.velocity_markers_y = []
                self.cm_per_second_per_pixel = None
            
        except Exception as e:
            print(f"Error detecting velocity markers: {e}")
            import traceback
            traceback.print_exc()
            self.velocity_marker_mask = None
    
    def calculate_flow_areas(self):
        """Calculate the area of signal above and below the centerline."""
        if self.current_image is None:
            messagebox.showinfo("Info", "Please load an image first.")
            return
        
        if not self.detected_line_segments:
            messagebox.showwarning("Warning", "Please detect the centerline first.")
            return
        
        if 'bounding_box' not in self.config:
            messagebox.showwarning("Warning", "Bounding box not defined in config.")
            return
        
        try:
            # Get analysis area boundaries
            bb = self.config['bounding_box']
            x_min_bb = bb.get('x_min', 0)
            y_min_bb = bb.get('y_min', 0)
            x_max_bb = bb.get('x_max', 0)
            y_max_bb = bb.get('y_max', 0)
            
            # Get analysis lines
            line1_x = self.analysis_line1_x.get()
            line2_x = self.analysis_line2_x.get()
            
            # Ensure lines are within bounding box
            line1_x = max(x_min_bb, min(line1_x, x_max_bb))
            line2_x = max(x_min_bb, min(line2_x, x_max_bb))
            
            if line1_x >= line2_x:
                messagebox.showwarning("Warning", "Invalid analysis lines. Line 2 must be > Line 1.")
                return
            
            # Calculate average centerline Y position
            all_y_values = []
            for segment in self.detected_line_segments:
                for point in segment:
                    x, y = point
                    # Only include points within the analysis area
                    if line1_x <= x <= line2_x:
                        all_y_values.append(y)
            
            if not all_y_values:
                messagebox.showwarning("Warning", "No centerline points found in analysis area.")
                return
            
            self.centerline_y = np.mean(all_y_values)
            
            # Extract the analysis region
            img_array = np.array(self.current_image)
            analysis_region = img_array[y_min_bb:y_max_bb, line1_x:line2_x]
            
            # Create mask for signal (non-black pixels)
            # Black is (0, 0, 0) or very close to it
            black_threshold = 10  # Pixels darker than this are considered black
            signal_mask = np.any(analysis_region > black_threshold, axis=2)
            
            # Apply axis marker mask if available
            if self.axis_marker_mask is not None:
                # Extract the corresponding region from the axis marker mask
                # The axis marker mask is in bounding box coordinates
                # We need to extract the part that overlaps with analysis region
                bb = self.config['bounding_box']
                bb_y_min = bb.get('y_min', 0)
                bb_x_min = bb.get('x_min', 0)
                
                # Calculate overlap region
                analysis_y_start = y_min_bb - bb_y_min
                analysis_y_end = analysis_y_start + analysis_region.shape[0]
                analysis_x_start = line1_x - bb_x_min
                analysis_x_end = analysis_x_start + analysis_region.shape[1]
                
                # Ensure indices are within bounds
                analysis_y_start = max(0, analysis_y_start)
                analysis_y_end = min(self.axis_marker_mask.shape[0], analysis_y_end)
                analysis_x_start = max(0, analysis_x_start)
                analysis_x_end = min(self.axis_marker_mask.shape[1], analysis_x_end)
                
                if (analysis_y_end > analysis_y_start and 
                    analysis_x_end > analysis_x_start):
                    # Extract marker mask for analysis region
                    marker_mask_region = self.axis_marker_mask[
                        analysis_y_start:analysis_y_end,
                        analysis_x_start:analysis_x_end
                    ]
                    
                    # Exclude marker pixels from signal mask
                    signal_mask = signal_mask & (~marker_mask_region)
            
            # Get local coordinates within analysis region
            # In image coordinates: y=0 is top, y increases downward
            # centerline_y is in global coordinates, need to convert to local
            local_centerline_y = int(self.centerline_y - y_min_bb)
            region_height = analysis_region.shape[0]
            
            # Ensure centerline is within region
            if local_centerline_y < 0:
                local_centerline_y = 0
            if local_centerline_y >= region_height:
                messagebox.showwarning("Warning", "Centerline outside analysis region.")
                return
            
            # Split signal into above and below centerline
            # Above centerline (positive flow): y < centerline_y (smaller y = higher on screen)
            # Below centerline (negative flow): y > centerline_y (larger y = lower on screen)
            above_mask = signal_mask.copy()
            above_mask[local_centerline_y:] = False  # Set everything at/below centerline to False
            
            below_mask = signal_mask.copy()
            below_mask[:local_centerline_y] = False  # Set everything above centerline to False
            
            # Calculate areas (number of signal pixels)
            self.area_above = int(np.sum(above_mask))
            self.area_below = int(np.sum(below_mask))
            
            # Store masks and region coordinates for visualization
            self.above_mask = above_mask
            self.below_mask = below_mask
            self.analysis_region_coords = (line1_x, y_min_bb, line2_x, y_max_bb)
            
            # Update display
            self.display_image()  # Refresh to show highlighted areas
            self.update_info_panel()
            
            # Calculate percentages
            total_area = self.area_above + self.area_below
            if total_area > 0:
                pos_percent = (self.area_above / total_area) * 100
                neg_percent = (self.area_below / total_area) * 100
            else:
                pos_percent = 0.0
                neg_percent = 0.0
            
            self.update_status(
                f"Areas calculated: Positive={self.area_above} px², Negative={self.area_below} px²"
            )
            
            # Add row to results table
            self.add_measurement_row(
                line1_x=line1_x,
                line2_x=line2_x,
                area_above=self.area_above,
                area_below=self.area_below,
                total_area=total_area,
                pos_percent=pos_percent,
                neg_percent=neg_percent,
                centerline_y=self.centerline_y
            )
            
            # Show results
            if total_area > 0:
                messagebox.showinfo(
                    "Flow Areas Calculated",
                    f"Positive Flow (above centerline): {self.area_above} px² ({pos_percent:.1f}%)\n"
                    f"Negative Flow (below centerline): {self.area_below} px² ({neg_percent:.1f}%)\n"
                    f"Total Signal Area: {total_area} px²"
                )
            else:
                messagebox.showinfo("No Signal", "No signal detected in the analysis area.")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to calculate areas: {e}")
            self.update_status(f"Error: {e}")
    
    def add_measurement_row(self, line1_x: int, line2_x: int, area_above: int, area_below: int,
                           total_area: int, pos_percent: float, neg_percent: float, centerline_y: float):
        """Add a row to the measurement results table."""
        # Get image name or use default
        image_name = self.current_image_path.name if self.current_image_path else "N/A"
        
        # Format values
        centerline_y_str = f"{centerline_y:.1f}" if centerline_y is not None else "N/A"
        pos_percent_str = f"{pos_percent:.2f}" if pos_percent > 0 else "0.00"
        neg_percent_str = f"{neg_percent:.2f}" if neg_percent > 0 else "0.00"
        
        # Convert areas from px² to cm using calibration factors
        # X: pixels → seconds (pixels_per_second)
        # Y: pixels → cm/s (cm_per_second_per_pixel)
        # Result: px² → (seconds × cm/s) = cm
        conversion_factor = self.calculate_area_conversion_factor()
        if conversion_factor is not None:
            area_above_cm = area_above * conversion_factor
            area_below_cm = area_below * conversion_factor
            total_area_cm = total_area * conversion_factor
            area_above_cm_str = f"{area_above_cm:.4f}"
            area_below_cm_str = f"{area_below_cm:.4f}"
            total_area_cm_str = f"{total_area_cm:.4f}"
        else:
            area_above_cm_str = "N/A"
            area_below_cm_str = "N/A"
            total_area_cm_str = "N/A"
        
        # Get current timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Insert row
        self.results_table.insert(
            "",
            tk.END,
            values=(
                image_name,
                str(line1_x),
                str(line2_x),
                str(area_above),
                str(area_below),
                str(total_area),
                area_above_cm_str,
                area_below_cm_str,
                total_area_cm_str,
                pos_percent_str,
                neg_percent_str,
                centerline_y_str,
                timestamp
            )
        )
        
        # Increment counter
        self.measurement_counter += 1
    
    def export_to_csv(self):
        """Export the measurement results table to a CSV file."""
        if not self.results_table.get_children():
            messagebox.showwarning("No Data", "No measurements to export. Please calculate flow areas first.")
            return
        
        # Ask user for file location
        file_path = filedialog.asksaveasfilename(
            title="Export Results to CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                
                # Write header row
                headers = [
                    "Image Name", "Line 1 X", "Line 2 X", "Area Above (px²)", "Area Below (px²)",
                    "Total Area (px²)", "Area Above (cm)", "Area Below (cm)", "Total Area (cm)",
                    "Positive %", "Negative %", "Centerline Y", "Timestamp"
                ]
                writer.writerow(headers)
                
                # Write data rows
                for item in self.results_table.get_children():
                    values = self.results_table.item(item, 'values')
                    writer.writerow(values)
            
            self.update_status(f"Results exported to {Path(file_path).name}")
            messagebox.showinfo("Export Successful", f"Results exported to:\n{file_path}")
            
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export CSV: {e}")
            self.update_status(f"Export error: {e}")
    
    def update_status(self, message: str):
        """Update the status bar."""
        self.status_bar.config(text=message)


def main():
    """Main function to run the application."""
    root = tk.Tk()
    
    # Try to load config from default location
    config_path = Path("config/us_config.yaml")
    if not config_path.exists():
        # Try alternative locations
        alt_paths = [
            Path(__file__).parent / "config" / "us_config.yaml",
            Path.cwd() / "config" / "us_config.yaml"
        ]
        for alt_path in alt_paths:
            if alt_path.exists():
                config_path = alt_path
                break
    
    app = ImageViewer(root, str(config_path))
    root.mainloop()


if __name__ == '__main__':
    main()

