import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from pygments import lex
from pygments.lexers import PythonLexer
from pygments.token import Token

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

def get_base_dir():
	if getattr(sys, 'frozen', False):
		documents = Path.home() / "Documents"
		app_dir = documents / "Project Tester"
		app_dir.mkdir(parents=True, exist_ok=True)
		return app_dir
	else:
		return Path(__file__).resolve().parent

def get_resource_path(relative_path):
	if getattr(sys, 'frozen', False):
		base_path = Path(sys._MEIPASS)
	else:
		base_path = Path(__file__).resolve().parent
	return base_path / relative_path

BASE_DIR = get_base_dir()
DATA_DIR = BASE_DIR / "data"
ASSETS_DIR = BASE_DIR / "assets"
PREDEFINED_INPUTS_PATH = BASE_DIR / "predefined_inputs.json"
CONFIG_PATH = BASE_DIR / "config.json"
FEEDBACK_TEMPLATE_PATH = BASE_DIR / "feedback_template.txt"

if getattr(sys, 'frozen', False):
	ICON_PATH = get_resource_path("assets/icon.png")
else:
	ICON_PATH = ASSETS_DIR / "icon.png"

GRADE_SCALE = {
    "5": (90, 100),
    "4": (80, 89),
    "3": (70, 79),
    "2": (60, 69),
    "1": (50, 59),
    "F": (0, 49),
}

GRADE_COLORS = {
    "5": "#00a526", 
    "4": "#689e03", 
    "3": "#b88a00",  
    "2": "#fd7e14", 
    "1": "#a70313",  
    "F": "#ff0000", 
}

class ToolTip:
	def __init__(self, widget, text):
		self.widget = widget
		self.text = text
		self.tooltip_window = None
		self.widget.bind("<Enter>", self.show_tooltip)
		self.widget.bind("<Leave>", self.hide_tooltip)
	
	def show_tooltip(self, event=None):
		if self.tooltip_window or not self.text:
			return
		x = self.widget.winfo_rootx() + 20
		y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
		self.tooltip_window = tk.Toplevel(self.widget)
		self.tooltip_window.wm_overrideredirect(True)
		self.tooltip_window.wm_geometry(f"+{x}+{y}")
		label = tk.Label(self.tooltip_window, text=self.text, background="#ffffe0", 
						relief="solid", borderwidth=1, font=("TkDefaultFont", 8))
		label.pack()
	
	def hide_tooltip(self, event=None):
		if self.tooltip_window:
			self.tooltip_window.destroy()
			self.tooltip_window = None

def get_python_executable():
	if getattr(sys, 'frozen', False):
		import os
		
		python_cmd = shutil.which('python')
		if python_cmd:
			return python_cmd
			
		python3_cmd = shutil.which('python3')
		if python3_cmd:
			return python3_cmd
			
		raise FileNotFoundError(
			"Python interpreter not found. Please ensure Python is installed and added to PATH.\n"
			"You can download Python from https://www.python.org/downloads/\n"
			"Make sure to check 'Add Python to PATH' during installation."
		)
	else:
		return sys.executable

class PythonTesterApp:
	def __init__(self, root: tk.Tk) -> None:
		self.root = root
		self.root.title("Project Tester")
		
		self.root.minsize(1024, 600)
		
		self.root.state('zoomed')
		
		if ICON_PATH.exists():
			try:
				self.root.iconphoto(True, tk.PhotoImage(file=str(ICON_PATH)))
			except Exception as e:
				print(f"Failed to load icon: {e}")
		
		copy_icon_path = ASSETS_DIR / "copy.png" if not getattr(sys, 'frozen', False) else get_resource_path("assets/copy.png")
		self.copy_icon = None
		if copy_icon_path.exists():
			try:
				original_icon = tk.PhotoImage(file=str(copy_icon_path))
				self.copy_icon = original_icon.subsample(6, 6)  
			except Exception as e:
				print(f"Failed to load copy icon: {e}")

		self.process: subprocess.Popen | None = None
		self.output_queue: queue.Queue[str] = queue.Queue()
		self.output_thread: threading.Thread | None = None

		self.file_var = tk.StringVar()
		self.predefined_inputs: list[str] = []
		self.zoom_level = 1.0
		self.submissions_dir: Path | None = None
		self.current_points = 100
		self.last_file_for_points = None
		self.feedback_text: ScrolledText | None = None  
		self._resize_scheduled = False
		self.feedback_collapsed = True
		self.code_viewer_zoom = 1.5  # Default zoom for code viewer
		self.files_viewer_zoom = 1.4  # Default zoom for data files viewer
		self.points_history: list[tuple[int, str]] = []  
		self.last_accessed_preset_index: int = -1
		self.last_sent_preset_index: int = -1  

		self._load_config()
		self._create_menu()
		self._build_layout()
		self._load_predefined_inputs()
		self._refresh_file_list()
		self._update_button_states()  
		self._poll_output_queue()
		self._setup_zoom_bindings()
		self._apply_zoom()  
		self._update_points_display() 
		self.root.protocol("WM_DELETE_WINDOW", self._on_close)

	def _center_window_on_parent(self, window: tk.Toplevel, width: int = None, height: int = None) -> None:
		window.update_idletasks()
		
		main_x = self.root.winfo_x()
		main_y = self.root.winfo_y()
		main_width = self.root.winfo_width()
		main_height = self.root.winfo_height()
		
		if width is None:
			width = window.winfo_reqwidth()
		if height is None:
			height = window.winfo_reqheight()
		
		x = main_x + (main_width - width) // 2
		y = main_y + (main_height - height) // 2
		
		x = max(0, x)
		y = max(0, y)
		
		window.geometry(f"{width}x{height}+{x}+{y}")

	def _create_menu(self) -> None:
		self.menubar = tk.Menu(self.root)
		self.root.config(menu=self.menubar)

		self.file_menu = tk.Menu(self.menubar, tearoff=0)
		self.menubar.add_cascade(label="File", menu=self.file_menu)
		self.file_menu.add_command(label="Extract Submissions", command=self._extract_submissions)
		self.file_menu.add_separator()
		self.file_menu.add_command(label="Import Predefined Inputs", command=self._import_predefined_inputs)
		self.file_menu.add_command(label="Export Predefined Inputs", command=self._export_predefined_inputs)
		self.file_menu.add_separator()
		self.file_menu.add_command(label="Settings", command=self._open_settings)
		self.file_menu.add_separator()
		self.file_menu.add_command(label="Exit", command=self._on_close)

		self.view_menu = tk.Menu(self.menubar, tearoff=0)
		self.menubar.add_cascade(label="View", menu=self.view_menu)
		self.view_menu.add_command(label="Zoom In", command=self._zoom_in, accelerator="Ctrl++")
		self.view_menu.add_command(label="Zoom Out", command=self._zoom_out, accelerator="Ctrl+-")
		self.view_menu.add_command(label="Reset Zoom", command=self._reset_zoom, accelerator="Ctrl+0")

	def _build_layout(self) -> None:
		self.root.columnconfigure(0, weight=3)
		self.root.columnconfigure(1, weight=2)
		self.root.rowconfigure(0, weight=0)  # Points frame
		self.root.rowconfigure(1, weight=1)  # Predefined inputs (expandable)
		self.root.rowconfigure(2, weight=0)  # Feedback frame  
		
		self.root.bind("<Configure>", self._on_window_resize)

		main_frame = ttk.Frame(self.root, padding=12)
		main_frame.grid(row=0, column=0, rowspan=3, sticky="nsew")
		main_frame.columnconfigure(0, weight=1)
		main_frame.rowconfigure(3, weight=1)

		header_row = ttk.Frame(main_frame)
		header_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
		header_row.columnconfigure(1, weight=1)
		
		ttk.Label(header_row, text="Submission File").grid(row=0, column=0, sticky="w")
		
		self.directory_label = ttk.Label(header_row, text="Directory: None", foreground="gray")
		self.directory_label.grid(row=0, column=1, sticky="w", padx=(20, 0))

		file_row = ttk.Frame(main_frame)
		file_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
		file_row.columnconfigure(0, weight=1)

		self.file_combo = ttk.Combobox(
			file_row,
			textvariable=self.file_var,
			state="readonly",
			postcommand=self._refresh_file_list,
		)
		self.file_combo.grid(row=0, column=0, sticky="ew", padx=(0, 6))

		refresh_button = ttk.Button(file_row, text="Refresh", command=self._refresh_file_list)
		refresh_button.grid(row=0, column=1, padx=(0, 6))

		browse_button = ttk.Button(file_row, text="Browse", command=self._browse_directory)
		browse_button.grid(row=0, column=2, padx=(0, 6))

		reset_files_button = ttk.Button(file_row, text="Reset Files", command=self._reset_files)
		reset_files_button.grid(row=0, column=3)

		controls = ttk.Frame(main_frame)
		controls.grid(row=2, column=0, sticky="ew", pady=(0, 8))
		controls.columnconfigure((0, 1, 2, 3, 4), weight=1)

		self.run_button = tk.Button(controls, text="▶ Run", command=self._run_selected_file,
									 relief="raised", cursor="hand2", bg="#90EE90", activebackground="#7CCD7C")
		self.run_button.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=2)

		self.stop_button = tk.Button(controls, text="■ Stop", command=self._stop_process, 
									  relief="raised", cursor="hand2", state="disabled")
		self.stop_button.grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=2)

		self.clear_button = tk.Button(controls, text="Clear", command=self._clear_terminal,
									   relief="raised", cursor="hand2")
		self.clear_button.grid(row=0, column=2, sticky="ew", padx=(0, 6), pady=2)

		self.open_code_button = tk.Button(controls, text="Open Code", command=self._open_code_viewer,
										   relief="raised", cursor="hand2")
		self.open_code_button.grid(row=0, column=3, sticky="ew", padx=(0, 6), pady=2)

		self.open_files_button = tk.Button(controls, text="Open Files", command=self._open_files_viewer,
											relief="raised", cursor="hand2")
		self.open_files_button.grid(row=0, column=4, sticky="ew", pady=2)

		terminal_frame = ttk.LabelFrame(main_frame, text="Terminal")
		terminal_frame.grid(row=3, column=0, sticky="nsew")
		terminal_frame.rowconfigure(0, weight=1)
		terminal_frame.columnconfigure(0, weight=1)

		self.output_text = ScrolledText(terminal_frame, wrap="word", height=20, state="disabled")
		self.output_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

		input_row = ttk.Frame(main_frame)
		input_row.grid(row=4, column=0, sticky="ew", pady=(8, 0))
		input_row.columnconfigure(0, weight=1)

		ttk.Label(input_row, text="Manual Input").grid(row=0, column=0, sticky="w")
		manual_entry_row = ttk.Frame(input_row)
		manual_entry_row.grid(row=1, column=0, sticky="ew")
		manual_entry_row.columnconfigure(0, weight=1)

		self.manual_input_var = tk.StringVar()
		self.manual_entry = ttk.Entry(manual_entry_row, textvariable=self.manual_input_var, width=50)
		self.manual_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
		self.manual_entry.bind("<Return>", lambda e: self._send_manual_input())

		send_manual_button = ttk.Button(manual_entry_row, text="Send", command=self._send_manual_input)
		send_manual_button.grid(row=0, column=1)

		points_frame = ttk.LabelFrame(self.root, text="Point Tracker", padding=8)
		points_frame.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 6))
		points_frame.columnconfigure(1, weight=1)

		ttk.Label(points_frame, text="Current Points:").grid(row=0, column=0, sticky="w", padx=(0, 6))
		
		points_grade_frame = ttk.Frame(points_frame)
		points_grade_frame.grid(row=0, column=1, sticky="ew")
		points_grade_frame.columnconfigure(2, weight=1)  
		
		self.points_display = ttk.Label(points_grade_frame, text="100", font=("TkDefaultFont", 8, "bold"), foreground="green")
		self.points_display.grid(row=0, column=0, sticky="w")
		
		if self.copy_icon:
			copy_points_button = tk.Button(points_grade_frame, image=self.copy_icon, command=self._copy_points, 
										   relief="flat", cursor="hand2", bd=0, bg=self.root.cget('bg'))
		else:
			copy_points_button = ttk.Button(points_grade_frame, text="📋", width=3, command=self._copy_points)
		copy_points_button.grid(row=0, column=1, sticky="w", padx=(4, 0))
		ToolTip(copy_points_button, "Copy")
		
		grade_container = ttk.Frame(points_grade_frame)
		grade_container.grid(row=0, column=3, sticky="e", padx=(0, 8))
		
		ttk.Label(grade_container, text="Grade: ").grid(row=0, column=0, sticky="e")
		
		self.grade_display = ttk.Label(grade_container, text="5", font=("TkDefaultFont", 8, "bold"), foreground="green")
		self.grade_display.grid(row=0, column=1, sticky="e")
		
		if self.copy_icon:
			copy_grade_button = tk.Button(grade_container, image=self.copy_icon, command=self._copy_grade,
										  relief="flat", cursor="hand2", bd=0, bg=self.root.cget('bg'))
		else:
			copy_grade_button = ttk.Button(grade_container, text="📋", width=3, command=self._copy_grade)
		copy_grade_button.grid(row=0, column=2, sticky="w", padx=(4, 0))
		ToolTip(copy_grade_button, "Copy")

		ttk.Label(points_frame, text="Adjust Points:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
		
		adjust_row = ttk.Frame(points_frame)
		adjust_row.grid(row=1, column=1, sticky="ew", pady=(6, 0))
		adjust_row.columnconfigure(2, weight=1)

		self.points_adjust_var = tk.StringVar(value="4")
		
		def validate_points_input(new_value):
			if new_value == "":
				return True
			try:
				value = int(new_value)
				return 1 <= value <= 100
			except ValueError:
				return False
		
		vcmd = (self.root.register(validate_points_input), '%P')
		
		minus_button = ttk.Button(adjust_row, text="-", command=self._decrease_points, width=3, takefocus=False)
		minus_button.grid(row=0, column=0, padx=(0, 3))
		
		self.points_adjust_entry = ttk.Entry(adjust_row, textvariable=self.points_adjust_var, 
											 width=4, validate='key', validatecommand=vcmd)
		self.points_adjust_entry.grid(row=0, column=1, sticky="w", padx=(0, 3))
		
		plus_button = ttk.Button(adjust_row, text="+", command=self._increase_points, width=3, takefocus=False)
		plus_button.grid(row=0, column=2,sticky="w", padx=(0, 6))
		
		history_button = ttk.Button(adjust_row, text="History", command=self._show_points_history, width=8)
		history_button.grid(row=0, column=3, sticky="e", padx=(0, 6))

		reset_button = ttk.Button(adjust_row, text="Reset", command=self._reset_points, width=8)
		reset_button.grid(row=0, column=4, sticky="e")

		sidebar = ttk.LabelFrame(self.root, text="Preset Inputs", padding=12)
		sidebar.grid(row=1, column=1, sticky="nsew", padx=(0, 12), pady=(6, 6))
		sidebar.columnconfigure(0, weight=1)
		sidebar.rowconfigure(1, weight=1)

		label_row = ttk.Frame(sidebar)
		label_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
		label_row.columnconfigure(0, weight=1)

		hotkeys_button = ttk.Button(label_row, text="Shortcuts", command=self._show_hotkeys_dialog)
		hotkeys_button.grid(row=0, column=0, sticky="w")

		move_up_button = ttk.Button(label_row, text="↑", width=3, command=self._move_predefined_up)
		move_up_button.grid(row=0, column=1, padx=(6, 3))

		move_down_button = ttk.Button(label_row, text="↓", width=3, command=self._move_predefined_down)
		move_down_button.grid(row=0, column=2)

		listbox_frame = ttk.Frame(sidebar)
		listbox_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 6))
		listbox_frame.columnconfigure(0, weight=1)
		listbox_frame.rowconfigure(0, weight=1)

		self.predefined_listbox = tk.Listbox(listbox_frame, height=15)
		self.predefined_listbox.grid(row=0, column=0, sticky="nsew")
		
		listbox_scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical", command=self.predefined_listbox.yview)
		listbox_scrollbar.grid(row=0, column=1, sticky="ns")
		self.predefined_listbox.config(yscrollcommand=listbox_scrollbar.set)
		
		self.predefined_listbox.bind("<Double-Button-1>", self._handle_predefined_double_click)
		self.predefined_listbox.bind("<Return>", lambda e: self._send_selected_predefined())
		self.predefined_listbox.bind("<space>", lambda e: self._handle_space_key())
		self.predefined_listbox.bind("<Control-e>", lambda e: self._edit_selected_predefined())
		self.predefined_listbox.bind("<Button-3>", self._show_context_menu)
		self.predefined_listbox.bind("<Control-Return>", lambda e: self._insert_row_below())
		self.predefined_listbox.bind("<Delete>", lambda e: self._remove_selected_predefined())
		self.predefined_listbox.bind("<<ListboxSelect>>", self._track_preset_selection)
		self.predefined_listbox.bind("<FocusIn>", lambda e: self._check_predefined_empty())
		
		self.context_menu = tk.Menu(self.predefined_listbox, tearoff=0)
		self.context_menu.add_command(label="Insert row below", command=self._insert_row_below)
		
		self.edit_entry = None
		self.edit_index = None

		predefined_buttons = ttk.Frame(sidebar)
		predefined_buttons.grid(row=2, column=0, sticky="ew", pady=(0, 12))
		predefined_buttons.columnconfigure(0, weight=1)
		predefined_buttons.columnconfigure(1, weight=1)

		remove_button = ttk.Button(predefined_buttons, text="Remove", command=self._remove_selected_predefined)
		remove_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

		send_button = ttk.Button(predefined_buttons, text="Send", command=self._send_selected_predefined)
		send_button.grid(row=0, column=1, sticky="ew")

		feedback_frame = ttk.LabelFrame(self.root, text="Feedback", padding=8)
		feedback_frame.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=(6, 12))
		feedback_frame.columnconfigure(0, weight=1)
		
		feedback_header = ttk.Frame(feedback_frame)
		feedback_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
		feedback_header.columnconfigure(0, weight=1)
		
		self.feedback_collapse_button = ttk.Button(feedback_header, text="▶ Show", width=12, command=self._toggle_feedback_collapse)
		self.feedback_collapse_button.grid(row=0, column=0, sticky="w")
		
		self.feedback_content_frame = ttk.Frame(feedback_frame)
		self.feedback_content_frame.grid(row=1, column=0, sticky="ew")
		self.feedback_content_frame.grid_remove()  
		self.feedback_content_frame.columnconfigure(0, weight=1)
		
		self.feedback_text = ScrolledText(self.feedback_content_frame, wrap="word", height=8, width=30)
		self.feedback_text.grid(row=0, column=0, sticky="ew", pady=(0, 6))
		
		feedback_buttons_frame = ttk.Frame(self.feedback_content_frame)
		feedback_buttons_frame.grid(row=1, column=0, sticky="ew")
		feedback_buttons_frame.columnconfigure(0, weight=1)
		
		reset_feedback_button = ttk.Button(feedback_buttons_frame, text="Reset", command=self._reset_feedback)
		reset_feedback_button.grid(row=0, column=1, sticky="e", padx=(16, 6))
		
		if self.copy_icon:
			copy_feedback_button = tk.Button(feedback_buttons_frame, image=self.copy_icon, command=self._copy_feedback,
											 relief="flat", cursor="hand2", bd=0, bg=self.root.cget('bg'))
		else:
			copy_feedback_button = ttk.Button(feedback_buttons_frame, text="📋", width=3, command=self._copy_feedback)
		copy_feedback_button.grid(row=0, column=0, sticky="e")
		ToolTip(copy_feedback_button, "Copy")
		
		self._load_feedback_template()

	def _refresh_file_list(self) -> None:
		if self.submissions_dir is None:
			self.file_combo["values"] = []
			if self.file_var.get():
				self.file_var.set("")
			self._update_directory_label()
			return
		
		if not self.submissions_dir.exists():
			messagebox.showwarning("Directory Missing", 
				f"The directory {self.submissions_dir} no longer exists.\nPlease browse for a new directory.")
			self.submissions_dir = None
			self._save_config()
			self.file_combo["values"] = []
			if self.file_var.get():
				self.file_var.set("")
			self._update_directory_label()
			return

		try:
			python_files = sorted(self.submissions_dir.glob("*.py"))
			file_names = [file.name for file in python_files]
		except OSError as err:
			messagebox.showerror("Directory Error", f"Could not read directory: {err}")
			file_names = []

		self.file_combo["values"] = file_names

		if file_names:
			if hasattr(self, 'last_opened_file') and self.last_opened_file in file_names:
				self.file_var.set(self.last_opened_file)
			elif not self.file_var.get() or self.file_var.get() not in file_names:
				self.file_var.set(file_names[0])
		else:
			self.file_var.set("")
		
		self._update_directory_label()
	
	def _update_directory_label(self) -> None:
		if self.submissions_dir is None:
			self.directory_label.config(text="Directory: None", foreground="gray")
		else:
			self.directory_label.config(text=f"Directory: {self.submissions_dir}", foreground="black")
		self._update_button_states()
	
	def _update_button_states(self) -> None:
		if self.submissions_dir is None:
			self.run_button.configure(state="disabled", bg=self.root.cget('bg'))
			self.open_code_button.configure(state="disabled")
			self.open_files_button.configure(state="disabled")
		else:
			if self.process and self.process.poll() is None:
				self.run_button.configure(state="disabled", bg=self.root.cget('bg'))
			else:
				self.run_button.configure(state="normal", bg="#90EE90", activebackground="#7CCD7C")
			self.open_code_button.configure(state="normal")
			self.open_files_button.configure(state="normal")
	
	def _on_window_resize(self, event: tk.Event) -> None:
		if event.widget != self.root:
			return
		
		if not hasattr(self, '_resize_scheduled') or not self._resize_scheduled:
			self._resize_scheduled = True
			self.root.after_idle(self._adjust_layout)
	
	def _adjust_layout(self) -> None:
		self._resize_scheduled = False
		
		window_width = self.root.winfo_width()
		
		screen_width = self.root.winfo_screenwidth()
		threshold_width = max(int(screen_width * 2 / 3), 1280)
		
		if window_width < threshold_width:
			self.root.columnconfigure(0, weight=5, uniform="equal")
			self.root.columnconfigure(1, weight=3, uniform="equal")
		else:
			self.root.columnconfigure(0, weight=3, uniform="")
			self.root.columnconfigure(1, weight=2, uniform="")
		
		self.root.update_idletasks()

	def _browse_directory(self) -> None:
		initial_dir = BASE_DIR
		if self.submissions_dir is not None and self.submissions_dir.exists():
			initial_dir = self.submissions_dir
		
		selected_file = filedialog.askopenfilename(
			title="Select Python File",
			initialdir=str(initial_dir),
			filetypes=[("Python files", "*.py"), ("All files", "*.*")]
		)
		
		if selected_file:
			file_path = Path(selected_file)
			if file_path.exists() and file_path.suffix == ".py":
				self.submissions_dir = file_path.parent
				self.last_opened_file = file_path.name
				self._save_config()
				self._refresh_file_list()
			else:
				messagebox.showerror("File Error", "Please select a valid Python file.")

	def _run_selected_file(self) -> None:
		if self.process and self.process.poll() is None:
			messagebox.showinfo("Process Running", "A process is already running. Stop it before starting a new one.")
			return

		if self.submissions_dir is None:
			messagebox.showwarning("No Directory", "Please browse and select a Python file first.")
			return

		selected_file = self.file_var.get()
		if not selected_file:
			messagebox.showwarning("No File Selected", "Please choose a submission file to run.")
			return

		if self.last_file_for_points != selected_file:
			self.current_points = 100
			self.last_file_for_points = selected_file
			self._update_points_display()

		self.last_opened_file = selected_file
		self._save_config()

		script_path = self.submissions_dir / selected_file
		if not script_path.exists():
			messagebox.showerror("File Missing", 
				f"Could not find {selected_file} in the current directory.\nDirectory may have changed. Please refresh or browse again.")
			self._refresh_file_list()
			return

		try:
			python_executable = get_python_executable()
		except FileNotFoundError as err:
			messagebox.showerror("Python Not Found", str(err))
			return

		try:
			creation_flags = 0
			if sys.platform == 'win32':
				creation_flags = subprocess.CREATE_NO_WINDOW
			
			env = os.environ.copy()
			env['PYTHONUNBUFFERED'] = '1'
			
			self.process = subprocess.Popen(
				[python_executable, '-u', str(script_path)],  
				cwd=str(script_path.parent),
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.STDOUT,
				text=True,
				bufsize=0,  
				creationflags=creation_flags,
				env=env,
			)
		except OSError as err:
			messagebox.showerror("Execution Error", f"Failed to start process: {err}")
			return

		self._clear_terminal()
		self._append_output(f"Running {selected_file}...\n")

		self.run_button.configure(state="disabled", bg=self.root.cget('bg'))
		self.stop_button.configure(state="normal", bg="#FF6B6B", activebackground="#EE5A5A")

		self.output_thread = threading.Thread(target=self._read_process_output, daemon=True)
		self.output_thread.start()

	def _stop_process(self) -> None:
		if self.process and self.process.poll() is None:
			self.process.terminate()
			try:
				self.process.wait(timeout=2)
			except subprocess.TimeoutExpired:
				self.process.kill()

		self._on_process_end()

	def _read_process_output(self) -> None:
		assert self.process is not None and self.process.stdout is not None
		
		buffer = ""
		while True:
			char = self.process.stdout.read(1)
			if not char:
				break
			
			buffer += char
			
			if char:
				self.output_queue.put(char)
				
		return_code = self.process.wait()
		self.output_queue.put(f"\nProcess exited with code {return_code}.\n")
		self.output_queue.put(None)  

	def _poll_output_queue(self) -> None:
		try:
			while True:
				item = self.output_queue.get_nowait()
				if item is None:
					self._on_process_end()
					break
				self._append_output(item)
		except queue.Empty:
			pass

		self.root.after(100, self._poll_output_queue)

	def _append_output(self, text: str) -> None:
		self.output_text.configure(state="normal")
		self.output_text.insert(tk.END, text)
		self.output_text.see(tk.END)
		self.output_text.configure(state="disabled")

	def _clear_terminal(self) -> None:
		self.output_text.configure(state="normal")
		self.output_text.delete("1.0", tk.END)
		self.output_text.configure(state="disabled")

	def _send_manual_input(self) -> None:
		value = self.manual_input_var.get()
		self._send_to_process(value)
		self.manual_input_var.set("")

	def _send_selected_predefined(self) -> None:
		selection = self.predefined_listbox.curselection()
		if selection:
			current_index = selection[0]
			self.last_sent_preset_index = current_index
			value = self.predefined_listbox.get(current_index)
			
			if not value.strip().startswith("#"):
				self._send_to_process(value)
			
			next_index = current_index + 1
			if next_index < self.predefined_listbox.size():
				self.predefined_listbox.selection_clear(0, tk.END)
				self.predefined_listbox.selection_set(next_index)
				self.predefined_listbox.see(next_index)
				self.last_accessed_preset_index = next_index

	def _handle_predefined_double_click(self, event: tk.Event) -> None:
		self._edit_selected_predefined()

	def _edit_selected_predefined(self) -> None:
		selection = self.predefined_listbox.curselection()
		if not selection:
			return
		
		if self.edit_entry:
			self._finish_edit()
			return
		
		index = selection[0]
		self.edit_index = index
		
		bbox = self.predefined_listbox.bbox(index)
		if not bbox:
			return
		
		x, y, width, height = bbox
		
		current_value = self.predefined_listbox.get(index)
		
		listbox_width = self.predefined_listbox.winfo_width() - 10
		
		base_font_size = 9
		zoomed_font_size = int(base_font_size * self.zoom_level)
		entry_font = ("TkDefaultFont", zoomed_font_size)
		
		self.edit_entry = tk.Entry(self.predefined_listbox, font=entry_font)
		self.edit_entry.insert(0, current_value)
		self.edit_entry.select_range(0, tk.END)
		self.edit_entry.place(x=0, y=y, width=listbox_width, height=height)
		self.edit_entry.focus_set()
		
		self.edit_entry.bind("<Return>", lambda e: self._finish_edit())
		self.edit_entry.bind("<Escape>", lambda e: self._cancel_edit())
		self.edit_entry.bind("<FocusOut>", lambda e: self._finish_edit())

	def _finish_edit(self) -> None:
		if not self.edit_entry or self.edit_index is None:
			return
		
		new_value = self.edit_entry.get()
		
		self.predefined_inputs[self.edit_index] = new_value
		self._save_predefined_inputs()
		self._reload_predefined_listbox()
		
		self.predefined_listbox.selection_set(self.edit_index)
		self.predefined_listbox.see(self.edit_index)
		
		self.edit_entry.destroy()
		self.edit_entry = None
		self.edit_index = None
		
		self.predefined_listbox.focus_set()

	def _cancel_edit(self) -> None:
		if not self.edit_entry:
			return
		
		self.edit_entry.destroy()
		self.edit_entry = None
		self.edit_index = None
		
		self.predefined_listbox.focus_set()

	def _handle_space_key(self) -> None:
		self._send_selected_predefined()
		return "break"  
	
	def _check_predefined_empty(self) -> None:
		if len(self.predefined_inputs) == 0:
			self.predefined_inputs.append("")
			self._save_predefined_inputs()
			self._reload_predefined_listbox()
			self.predefined_listbox.selection_set(0)
	
	def _show_hotkeys_dialog(self) -> None:
		hotkeys_window = tk.Toplevel(self.root)
		hotkeys_window.title("Keyboard Shortcuts")
		hotkeys_window.transient(self.root)
		hotkeys_window.grab_set()
		self._center_window_on_parent(hotkeys_window, 550, 400)
		
		main_frame = ttk.Frame(hotkeys_window, padding=20)
		main_frame.pack(fill="both", expand=True)
		
		title_label = ttk.Label(main_frame, text="Preset Inputs - Keyboard Shortcuts", 
								font=("TkDefaultFont", int(12 * self.zoom_level), "bold"))
		title_label.pack(pady=(0, 20))
		
		canvas = tk.Canvas(main_frame, highlightthickness=0)
		scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
		scrollable_frame = ttk.Frame(canvas)
		
		scrollable_frame.bind(
			"<Configure>",
			lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
		)
		
		canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
		canvas.configure(yscrollcommand=scrollbar.set)
		
		scrollable_frame.columnconfigure(0, minsize=180)
		scrollable_frame.columnconfigure(1, weight=1)
		
		shortcuts = [
			("Enter / Space", "Send selected input to terminal"),
			("Ctrl+Enter", "Insert new row below selection"),
			("Double Click", "Edit selected input"),
			("Ctrl+E", "Edit selected input"),
			("Del", "Remove selected input"),
			("↑ / ↓ Buttons", "Move selected input up or down"),
		]
		
		key_header = ttk.Label(scrollable_frame, text="Key Binding", 
							   font=("TkDefaultFont", int(10 * self.zoom_level), "bold"))
		key_header.grid(row=0, column=0, sticky="w", padx=(0, 20), pady=(0, 5))
		
		desc_header = ttk.Label(scrollable_frame, text="Action", 
							    font=("TkDefaultFont", int(10 * self.zoom_level), "bold"))
		desc_header.grid(row=0, column=1, sticky="w", pady=(0, 5))
		
		separator1 = ttk.Separator(scrollable_frame, orient="horizontal")
		separator1.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
		
		for idx, (key, description) in enumerate(shortcuts):
			row_num = idx + 2
			
			key_label = ttk.Label(scrollable_frame, text=key, 
								 font=("TkDefaultFont", int(9 * self.zoom_level), "bold"))
			key_label.grid(row=row_num, column=0, sticky="w", padx=(0, 20), pady=5)
			
			desc_label = ttk.Label(scrollable_frame, text=description, 
								  font=("TkDefaultFont", int(9 * self.zoom_level)))
			desc_label.grid(row=row_num, column=1, sticky="w", pady=5)
		
		canvas.pack(side="left", fill="both", expand=True)
		scrollbar.pack(side="right", fill="y")
		
		def on_mousewheel(event):
			canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
		
		hotkeys_window.bind("<MouseWheel>", on_mousewheel)
	
	def _send_to_process(self, text: str) -> None:
		if not self.process or self.process.poll() is not None or not self.process.stdin:
			messagebox.showwarning("No Active Process", "Start a process before sending input.")
			return

		try:
			self.process.stdin.write(text + "\n")
			self.process.stdin.flush()
		except OSError as err:
			messagebox.showerror("Input Error", f"Failed to send input: {err}")
			return

		self._append_output(f"> {text}\n")

	def _track_preset_selection(self, event=None) -> None:
		selection = self.predefined_listbox.curselection()
		if selection:
			self.last_accessed_preset_index = selection[0]

	def _find_associated_checklist(self) -> str:
		"""Find checklist for the currently highlighted line."""
		index_to_use = self.last_accessed_preset_index
		
		if not self.predefined_inputs or index_to_use < 0:
			return "No checklist found"
		
		for i in range(index_to_use, -1, -1):
			item = self.predefined_inputs[i].strip()
			if item.startswith("# Checklist"):
				return item
		
		return "No checklist found"

	def _remove_selected_predefined(self) -> None:
		selection = self.predefined_listbox.curselection()
		if not selection:
			return

		index = selection[0]
		del self.predefined_inputs[index]
		self._save_predefined_inputs()
		self._reload_predefined_listbox()
		
		if len(self.predefined_inputs) > 0:
			if index < len(self.predefined_inputs):
				self.predefined_listbox.selection_set(index)
				self.predefined_listbox.see(index)
			else:
				self.predefined_listbox.selection_set(len(self.predefined_inputs) - 1)
				self.predefined_listbox.see(len(self.predefined_inputs) - 1)

	def _move_predefined_up(self) -> None:
		selection = self.predefined_listbox.curselection()
		if not selection:
			return

		index = selection[0]
		if index == 0:
			return  # Already at the top

		self.predefined_inputs[index], self.predefined_inputs[index - 1] = \
			self.predefined_inputs[index - 1], self.predefined_inputs[index]
		
		self._save_predefined_inputs()
		self._reload_predefined_listbox()
		
		self.predefined_listbox.selection_set(index - 1)
		self.predefined_listbox.see(index - 1)

	def _move_predefined_down(self) -> None:
		selection = self.predefined_listbox.curselection()
		if not selection:
			return

		index = selection[0]
		if index >= len(self.predefined_inputs) - 1:
			return  # Already at the bottom

		self.predefined_inputs[index], self.predefined_inputs[index + 1] = \
			self.predefined_inputs[index + 1], self.predefined_inputs[index]
		
		self._save_predefined_inputs()
		self._reload_predefined_listbox()
		
		self.predefined_listbox.selection_set(index + 1)
		self.predefined_listbox.see(index + 1)

	def _show_context_menu(self, event: tk.Event) -> None:
		index = self.predefined_listbox.nearest(event.y)
		if index >= 0:
			self.predefined_listbox.selection_clear(0, tk.END)
			self.predefined_listbox.selection_set(index)
			try:
				self.context_menu.tk_popup(event.x_root, event.y_root)
			finally:
				self.context_menu.grab_release()

	def _insert_row_below(self) -> None:
		selection = self.predefined_listbox.curselection()
		
		if not selection:
			if len(self.predefined_inputs) == 0:
				self.predefined_inputs.append("")
				self._save_predefined_inputs()
				self._reload_predefined_listbox()
				self.predefined_listbox.selection_set(0)
				self.predefined_listbox.see(0)
				self._edit_selected_predefined()
			return
		
		index = selection[0]
		self.predefined_inputs.insert(index + 1, "")
		self._save_predefined_inputs()
		self._reload_predefined_listbox()
		
		self.predefined_listbox.selection_clear(0, tk.END)
		self.predefined_listbox.selection_set(index + 1)
		self.predefined_listbox.see(index + 1)
		
		self._edit_selected_predefined()

	def _adjust_points(self) -> None:
		try:
			adjustment_str = self.points_adjust_var.get().strip()
			adjustment = int(float(adjustment_str))  
			
			self.current_points += adjustment
			self.current_points = max(0, min(100, self.current_points))
			
			self._update_points_display()
			self._save_config()
		except ValueError:
			messagebox.showerror("Invalid Input", "Please enter a valid number (e.g., -4, +5, or 3)")
	
	def _decrease_points(self) -> None:
		try:
			adjustment = int(self.points_adjust_var.get().strip())
			self.current_points -= adjustment
			self.current_points = max(0, min(100, self.current_points))
			
			checklist = self._find_associated_checklist()
			self.points_history.append((-adjustment, checklist))
			
			self._update_points_display()
			self._save_config()
		except ValueError:
			messagebox.showerror("Invalid Input", "Please enter a valid number between 1 and 100")
	
	def _increase_points(self) -> None:
		try:
			adjustment = int(self.points_adjust_var.get().strip())
			self.current_points += adjustment
			self.current_points = max(0, min(100, self.current_points))
			
			checklist = self._find_associated_checklist()
			self.points_history.append((adjustment, checklist))
			
			self._update_points_display()
			self._save_config()
		except ValueError:
			messagebox.showerror("Invalid Input", "Please enter a valid number between 1 and 100")
	
	def _show_points_history(self) -> None:
		if not self.points_history:
			messagebox.showinfo("Points History", "No point adjustments have been made yet.")
			return
		
		history_window = tk.Toplevel(self.root)
		history_window.title("Points History")
		
		base_width = 600
		base_height = 400
		zoomed_width = int(base_width * self.zoom_level)
		zoomed_height = int(base_height * self.zoom_level)
		self._center_window_on_parent(history_window, zoomed_width, zoomed_height)
		
		padx_val = int(10 * self.zoom_level)
		pady_val = int(10 * self.zoom_level)
		
		text_frame = ttk.Frame(history_window)
		text_frame.pack(fill="both", expand=True, padx=padx_val, pady=pady_val)
		
		base_font_size = 10
		zoomed_font_size = int(base_font_size * self.zoom_level)
		
		history_text = ScrolledText(text_frame, wrap="word", font=("Consolas", zoomed_font_size))
		history_text.pack(fill="both", expand=True)
		
		for i, (adjustment, checklist) in enumerate(self.points_history, 1):
			sign = "+" if adjustment > 0 else ""
			history_text.insert("end", f"{i}. {sign}{adjustment}: {checklist}\n")
		
		history_text.config(state="disabled")
		
		button_pady = int(5 * self.zoom_level)
		ttk.Button(history_window, text="Close", command=history_window.destroy).pack(pady=button_pady)

	def _reset_points(self) -> None:
		self.current_points = 100
		self.points_adjust_var.set("4")
		self.points_history.clear()  
		self._update_points_display()
		self._save_config()

	def _update_points_display(self) -> None:
		grade = self._calculate_grade(self.current_points)
		color = GRADE_COLORS[grade]
		
		self.points_display.config(text=f"{int(self.current_points)}", foreground=color)
		
		self.grade_display.config(text=grade, foreground=color)
	
	def _calculate_grade(self, points: float) -> str:
		for grade, (min_points, max_points) in GRADE_SCALE.items():
			if min_points <= points <= max_points:
				return grade
		return "F"
	
	def _copy_to_clipboard(self, text: str) -> None:
		self.root.clipboard_clear()
		self.root.clipboard_append(text)
		self.root.update()  
	
	def _copy_points(self) -> None:
		text = f"{int(self.current_points)}"
		self._copy_to_clipboard(text)
	
	def _copy_grade(self) -> None:
		grade = self._calculate_grade(self.current_points)
		self._copy_to_clipboard(grade)
	
	def _copy_points_and_grade(self) -> None:
		grade = self._calculate_grade(self.current_points)
		text = f"Points: {int(self.current_points)} | Grade: {grade}"
		self._copy_to_clipboard(text)
	
	def _copy_feedback(self) -> None:
		if self.feedback_text:
			feedback_content = self.feedback_text.get("1.0", "end-1c")
			self._copy_to_clipboard(feedback_content)

	def _load_feedback_template(self) -> None:
		if not self.feedback_text:
			return
		
		default_template = ""
		
		if FEEDBACK_TEMPLATE_PATH.exists():
			try:
				template_content = FEEDBACK_TEMPLATE_PATH.read_text(encoding="utf-8")
			except Exception as e:
				template_content = default_template
				print(f"Failed to load feedback template: {e}")
		else:
			template_content = default_template
			try:
				FEEDBACK_TEMPLATE_PATH.write_text(template_content, encoding="utf-8")
			except Exception as e:
				print(f"Failed to create default feedback template: {e}")
		
		self.feedback_text.delete("1.0", tk.END)
		self.feedback_text.insert("1.0", template_content)
	
	def _reset_feedback(self) -> None:
		self._load_feedback_template()
	
	def _toggle_feedback_collapse(self) -> None:
		if self.feedback_collapsed:
			self.feedback_content_frame.grid()
			self.feedback_collapse_button.config(text="▼ Hide")
			self.feedback_collapsed = False
		else:
			self.feedback_content_frame.grid_remove()
			self.feedback_collapse_button.config(text="▶ Show")
			self.feedback_collapsed = True

	def _load_predefined_inputs(self) -> None:
		if PREDEFINED_INPUTS_PATH.exists():
			try:
				data = json.loads(PREDEFINED_INPUTS_PATH.read_text(encoding="utf-8"))
				if isinstance(data, list):
					self.predefined_inputs = [str(item) for item in data]
			except json.JSONDecodeError:
				messagebox.showwarning(
					"Predefined Inputs",
					"The predefined inputs file is corrupted. Starting with an empty list.",
				)
				self.predefined_inputs = []
		else:
			self.predefined_inputs = []
		
		if len(self.predefined_inputs) == 0:
			self.predefined_inputs.append("")
			self._save_predefined_inputs()

		self._reload_predefined_listbox()
		
		if len(self.predefined_inputs) > 0:
			self.predefined_listbox.selection_set(0)

	def _import_predefined_inputs(self) -> None:
		file_path = filedialog.askopenfilename(
			title="Import Predefined Inputs",
			filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
			defaultextension=".json"
		)
		
		if not file_path:
			return
		
		try:
			data = json.loads(Path(file_path).read_text(encoding="utf-8"))
			if not isinstance(data, list):
				messagebox.showerror("Import Error", "The file must contain a JSON array.")
				return
			
			self.predefined_inputs = [str(item) for item in data]
			self._save_predefined_inputs()
			self._reload_predefined_listbox()
			messagebox.showinfo("Import Success", f"Imported {len(self.predefined_inputs)} items.")
		except json.JSONDecodeError:
			messagebox.showerror("Import Error", "The file is not a valid JSON file.")
		except Exception as e:
			messagebox.showerror("Import Error", f"Failed to import file: {e}")

	def _export_predefined_inputs(self) -> None:
		if not self.predefined_inputs:
			messagebox.showwarning("Export Warning", "No predefined inputs to export.")
			return
		
		file_path = filedialog.asksaveasfilename(
			title="Export Predefined Inputs",
			filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
			defaultextension=".json"
		)
		
		if not file_path:
			return
		
		try:
			Path(file_path).write_text(json.dumps(self.predefined_inputs, indent=2), encoding="utf-8")
			messagebox.showinfo("Export Success", f"Exported {len(self.predefined_inputs)} items to:\n{file_path}")
		except Exception as e:
			messagebox.showerror("Export Error", f"Failed to export file: {e}")
	
	def _extract_submissions(self) -> None:
		extract_window = tk.Toplevel(self.root)
		extract_window.title("Extract Submissions")
		extract_window.transient(self.root)
		extract_window.grab_set()
		self._center_window_on_parent(extract_window, 600, 300)
		
		main_frame = ttk.Frame(extract_window, padding=20)
		main_frame.pack(fill="both", expand=True)
		main_frame.columnconfigure(1, weight=1)
		
		ttk.Label(main_frame, text="Source Directory:", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 5))
		
		source_frame = ttk.Frame(main_frame)
		source_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 20))
		source_frame.columnconfigure(0, weight=1)
		
		source_var = tk.StringVar()
		source_entry = ttk.Entry(source_frame, textvariable=source_var, state="readonly")
		source_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
		
		def browse_source():
			file_path = filedialog.askopenfilename(
				title="Select a ZIP file (parent folder will be used)",
				filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
				initialdir=source_var.get() if source_var.get() else None
			)
			if file_path:
				parent_dir = str(Path(file_path).parent)
				source_var.set(parent_dir)
		
		ttk.Button(source_frame, text="Browse...", command=browse_source).grid(row=0, column=1)
		
		ttk.Label(main_frame, text="Destination Directory:", font=("TkDefaultFont", 10, "bold")).grid(row=2, column=0, sticky="w", pady=(0, 5))
		
		dest_frame = ttk.Frame(main_frame)
		dest_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0, 20))
		dest_frame.columnconfigure(0, weight=1)
		
		dest_var = tk.StringVar()
		dest_entry = ttk.Entry(dest_frame, textvariable=dest_var, state="readonly")
		dest_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
		
		def browse_dest():
			directory = filedialog.askdirectory(title="Select Destination Directory", mustexist=True)
			if directory:
				dest_var.set(directory)
		
		ttk.Button(dest_frame, text="Browse...", command=browse_dest).grid(row=0, column=1)
		
		progress_var = tk.StringVar(value="")
		progress_label = ttk.Label(main_frame, textvariable=progress_var, foreground="blue")
		progress_label.grid(row=4, column=0, columnspan=3, pady=(0, 10))
		
		button_frame = ttk.Frame(main_frame)
		button_frame.grid(row=5, column=0, columnspan=3)
		
		def start_extraction():
			source_dir = source_var.get()
			dest_dir = dest_var.get()
			
			if not source_dir or not dest_dir:
				messagebox.showwarning("Missing Information", "Please select both source and destination directories.")
				return
			
			source_path = Path(source_dir)
			dest_path = Path(dest_dir)
			
			if not source_path.exists():
				messagebox.showerror("Error", "Source directory does not exist.")
				return
			
			if not dest_path.exists():
				messagebox.showerror("Error", "Destination directory does not exist.")
				return
			
			pattern = r"Submit your project work \(Closes at \d{4}-\d{2}-\d{2} \d{2}_\d{2}\)-(.+)-archive\.zip"
			
			zip_files = list(source_path.glob("*.zip"))
			matched_files = []
			
			for zip_file in zip_files:
				match = re.match(pattern, zip_file.name)
				if match:
					name = match.group(1)
					matched_files.append((zip_file, name))
			
			if not matched_files:
				messagebox.showinfo("No Files", "No matching zip files found in the source directory.")
				return
			
			progress_var.set(f"Found {len(matched_files)} submission(s). Extracting...")
			extract_window.update()
			
			success_count = 0
			error_count = 0
			
			for count, (zip_file, name) in enumerate(matched_files, start=1):
				try:
					temp_extract_path = dest_path / f"_temp_{name}"
					
					with zipfile.ZipFile(zip_file, 'r') as zip_ref:
						zip_ref.extractall(temp_extract_path)
					
					top_dir = temp_extract_path / "top"
					
					if top_dir.exists() and top_dir.is_dir():
						final_dest = dest_path / f"{count} - {name}"
						
						if final_dest.exists():
							shutil.rmtree(final_dest)
						
						shutil.move(str(top_dir), str(final_dest))
						success_count += 1
					else:
						error_count += 1
						print(f"Warning: 'top' directory not found in {zip_file.name}")
					
					if temp_extract_path.exists():
						shutil.rmtree(temp_extract_path)
					
					progress_var.set(f"Processing: {count}/{len(matched_files)}")
					extract_window.update()
					
				except Exception as e:
					error_count += 1
					print(f"Error extracting {zip_file.name}: {e}")
			
			progress_var.set(f"Complete! Success: {success_count}, Errors: {error_count}")
			messagebox.showinfo("Extraction Complete", 
							   f"Successfully extracted: {success_count}\nErrors: {error_count}\n\nDestination: {dest_dir}")
		
		ttk.Button(button_frame, text="Extract", command=start_extraction, width=15).pack(side="left", padx=5)
		ttk.Button(button_frame, text="Cancel", command=extract_window.destroy, width=15).pack(side="left", padx=5)

	def _open_settings(self) -> None:
		settings_window = tk.Toplevel(self.root)
		settings_window.title("Settings")
		settings_window.transient(self.root)
		settings_window.grab_set()
		self._center_window_on_parent(settings_window, 600, 500)
		
		notebook = ttk.Notebook(settings_window)
		notebook.pack(fill="both", expand=True, padx=10, pady=10)
		
		data_tab = ttk.Frame(notebook)
		notebook.add(data_tab, text="Data Files")
		
		label = ttk.Label(data_tab, text="Stored Data Files (.txt):")
		label.pack(anchor="w", pady=(10, 5), padx=10)
		
		list_frame = ttk.Frame(data_tab)
		list_frame.pack(fill="both", expand=True, pady=(0, 10), padx=10)
		
		scrollbar = ttk.Scrollbar(list_frame)
		scrollbar.pack(side="right", fill="y")
		
		data_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=("TkDefaultFont", 11))
		data_listbox.pack(side="left", fill="both", expand=True)
		scrollbar.config(command=data_listbox.yview)
		
		def refresh_data_files():
			data_listbox.delete(0, tk.END)
			if DATA_DIR.exists():
				for file in sorted(DATA_DIR.glob("*.txt")):
					if file.name != "feedback_template.txt":  
						data_listbox.insert(tk.END, file.name)
		
		refresh_data_files()
		
		buttons_frame = ttk.Frame(data_tab)
		buttons_frame.pack(fill="x", padx=10, pady=(0, 10))
		
		def add_data_file():
			file_path = filedialog.askopenfilename(
				title="Select Data File",
				filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
			)
			if file_path:
				try:
					source = Path(file_path)
					dest = DATA_DIR / source.name
					shutil.copy(source, dest)
					refresh_data_files()
				except Exception as e:
					messagebox.showerror("Error", f"Failed to add file: {e}")
		
		def remove_data_file():
			selection = data_listbox.curselection()
			if not selection:
				messagebox.showwarning("No Selection", "Please select a file to remove.")
				return
			
			filename = data_listbox.get(selection[0])
			file_path = DATA_DIR / filename
			
			if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete {filename}?"):
				try:
					file_path.unlink()
					refresh_data_files()
				except Exception as e:
					messagebox.showerror("Error", f"Failed to remove file: {e}")
		
		add_button = ttk.Button(buttons_frame, text="Add File", command=add_data_file)
		add_button.pack(side="left", padx=(0, 5))
		
		remove_button = ttk.Button(buttons_frame, text="Remove File", command=remove_data_file)
		remove_button.pack(side="left")
		
		template_tab = ttk.Frame(notebook)
		notebook.add(template_tab, text="Feedback Template")
		
		template_label = ttk.Label(template_tab, text="Edit the feedback template (will be loaded each time):")
		template_label.pack(anchor="w", pady=(10, 5), padx=10)
		
		template_text_frame = ttk.Frame(template_tab)
		template_text_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
		
		template_text = ScrolledText(template_text_frame, wrap="word", height=15, font=("TkDefaultFont", 11))
		template_text.pack(fill="both", expand=True)
		
		default_template = " "
		if FEEDBACK_TEMPLATE_PATH.exists():
			try:
				template_content = FEEDBACK_TEMPLATE_PATH.read_text(encoding="utf-8")
			except Exception as e:
				template_content = default_template
		else:
			template_content = default_template
		
		template_text.insert("1.0", template_content)
		
		def save_template():
			try:
				new_template = template_text.get("1.0", "end-1c")
				FEEDBACK_TEMPLATE_PATH.write_text(new_template, encoding="utf-8")
				messagebox.showinfo("Success", "Feedback template saved successfully!")
				if self.feedback_text:
					self._load_feedback_template()
			except Exception as e:
				messagebox.showerror("Error", f"Failed to save template: {e}")
		
		save_button = ttk.Button(template_tab, text="Save Template", command=save_template)
		save_button.pack(pady=10)
		
		close_button = ttk.Button(settings_window, text="Close", command=settings_window.destroy)
		close_button.pack(pady=10)
	
	def _reset_files(self) -> None:
		if not DATA_DIR.exists() or not list(DATA_DIR.glob("*.txt")):
			messagebox.showwarning("No Data Files", "No stored data files found. Please add files in Settings.")
			return
		
		if self.submissions_dir is None:
			messagebox.showwarning("No Directory", "Please browse and select a directory first.")
			return
		
		if not self.submissions_dir.exists():
			messagebox.showerror("Error", 
				f"The directory {self.submissions_dir} no longer exists.\nPlease browse for a new directory.")
			self.submissions_dir = None
			self._save_config()
			return
		
		message = "This will delete matching files in the current directory and copy stored data files. Continue?"
		if not messagebox.askyesno("Confirm Reset", message):
			return
		
		try:
			for data_file in DATA_DIR.glob("*.txt"):
				target_file = self.submissions_dir / data_file.name
				if target_file.exists():
					target_file.unlink()
			
			copied_count = 0
			for data_file in DATA_DIR.glob("*.txt"):
				dest = self.submissions_dir / data_file.name
				shutil.copy(data_file, dest)
				copied_count += 1
			
			messagebox.showinfo("Success", f"Reset complete. Copied {copied_count} file(s) to:\n{self.submissions_dir}")
		except Exception as e:
			messagebox.showerror("Error", f"Failed to reset files: {e}")

	def _open_code_viewer(self) -> None:
		if self.submissions_dir is None:
			messagebox.showwarning("No Directory", "Please browse and select a Python file first.")
			return
		
		selected_file = self.file_var.get()
		if not selected_file:
			messagebox.showwarning("No File Selected", "Please select a Python file to view.")
			return
		
		script_path = self.submissions_dir / selected_file
		if not script_path.exists():
			messagebox.showerror("File Missing", f"Could not find {selected_file}.")
			return
		
		try:
			code_content = script_path.read_text(encoding="utf-8")
		except Exception as e:
			messagebox.showerror("Error", f"Failed to read file: {e}")
			return
		
		viewer = tk.Toplevel(self.root)
		viewer.title(f"Code Viewer - {selected_file}")
		
		screen_width = viewer.winfo_screenwidth()
		screen_height = viewer.winfo_screenheight()
		
		window_width = int(screen_width * 1 / 2)
		window_height = screen_height
		
		main_x = self.root.winfo_x()
		main_y = self.root.winfo_y()
		viewer.geometry(f"{window_width}x{window_height}+{main_x}+{main_y}")
		viewer.configure(bg="#1E1E1E")
		
		viewer.zoom_level = self.code_viewer_zoom
		
		open_count = code_content.count('open(')
		close_count = code_content.count('.close(')
		is_balanced = open_count == close_count
		counter_bg = "#2D5016" if is_balanced else "#5A1A1A"  
		counter_fg = "#90EE90" if is_balanced else "#FF6B6B"  
		
		top_bar = tk.Frame(viewer, bg="#1E1E1E")
		top_bar.pack(fill="x", padx=5, pady=(5, 0))
		
		search_frame = tk.Frame(top_bar, bg="#1E1E1E")
		search_frame.pack(side="left", padx=5)
		
		initial_search_font_size = int(9 * viewer.zoom_level)
		
		search_label = tk.Label(search_frame, text="Search:", bg="#1E1E1E", fg="#D4D4D4", font=("Consolas", initial_search_font_size))
		search_label.pack(side="left", padx=(0, 5))
		
		search_entry = tk.Entry(search_frame, bg="#3C3C3C", fg="#D4D4D4", insertbackground="#FFFFFF", 
								font=("Consolas", initial_search_font_size), width=20, relief="solid", borderwidth=1)
		search_entry.pack(side="left", padx=(0, 5))
		
		search_result_label = tk.Label(search_frame, text="0/0", bg="#1E1E1E", fg="#858585", 
								   font=("Consolas", initial_search_font_size), width=8)
		search_result_label.pack(side="left", padx=(0, 5))
		
		prev_button = tk.Button(search_frame, text="◀", bg="#3C3C3C", fg="#D4D4D4", 
								font=("Consolas", initial_search_font_size), width=3, relief="solid", borderwidth=1)
		prev_button.pack(side="left", padx=(0, 2))
		
		next_button = tk.Button(search_frame, text="▶", bg="#3C3C3C", fg="#D4D4D4", 
								font=("Consolas", initial_search_font_size), width=3, relief="solid", borderwidth=1)
		next_button.pack(side="left")
		
		counter_label = tk.Label(top_bar, 
								 text=f"open(): {open_count} | close(): {close_count}",
								 bg=counter_bg,
								 fg=counter_fg,
								 font=("Consolas", int(10 * viewer.zoom_level), "bold"),
								 padx=10,
								 pady=5,
								 relief="solid",
								 borderwidth=1)
		counter_label.pack(side="right", padx=5)
		
		frame = tk.Frame(viewer, bg="#1E1E1E")
		frame.pack(fill="both", expand=True, padx=5, pady=(0, 5))
		
		text_frame = tk.Frame(frame, bg="#1E1E1E")
		text_frame.pack(fill="both", expand=True)
		
		v_scrollbar = tk.Scrollbar(text_frame, bg="#252526", troughcolor="#1E1E1E")
		v_scrollbar.pack(side="right", fill="y")
		
		h_scrollbar = tk.Scrollbar(frame, orient="horizontal", bg="#252526", troughcolor="#1E1E1E")
		h_scrollbar.pack(side="bottom", fill="x")
		
		initial_font_size = int(10 * viewer.zoom_level)
		
		line_numbers = tk.Text(text_frame, wrap="none",
							   width=5,
							   font=("Consolas", initial_font_size),
							   bg="#1E1E1E",
							   fg="#858585",  
							   state="disabled",
							   borderwidth=0,
							   highlightthickness=0,
							   padx=5,
							   takefocus=0)
		line_numbers.pack(side="left", fill="y")
		
		text_widget = tk.Text(text_frame, wrap="none", 
							  yscrollcommand=v_scrollbar.set,
							  xscrollcommand=h_scrollbar.set,
							  font=("Consolas", initial_font_size),
							  bg="#1E1E1E",
							  fg="#D4D4D4",
							  insertbackground="#FFFFFF",
							  selectbackground="#264F78",
							  selectforeground="#D4D4D4",
							  borderwidth=0,
							  highlightthickness=0)
		text_widget.pack(side="left", fill="both", expand=True)
		
		def on_text_scroll(*args):
			line_numbers.yview_moveto(args[0])
			v_scrollbar.set(*args)
		
		text_widget.config(yscrollcommand=on_text_scroll)
		v_scrollbar.config(command=lambda *args: (text_widget.yview(*args), line_numbers.yview(*args)))
		h_scrollbar.config(command=text_widget.xview)
		
		text_widget.insert("1.0", code_content)
		
		num_lines = code_content.count('\n') + 1
		line_numbers.config(state="normal")
		line_numbers.insert("1.0", "\n".join(str(i) for i in range(1, num_lines + 1)))
		line_numbers.config(state="disabled")
		
		self._apply_python_syntax_highlighting(text_widget, code_content)
		text_widget.config(state="disabled")
		
		viewer.search_matches = []
		viewer.current_match = -1
		text_widget.tag_config("search_highlight", background="#FFA500", foreground="#000000")
		text_widget.tag_config("current_search_highlight", background="#FF4500", foreground="#FFFFFF")
		
		def perform_search(event=None):
			search_term = search_entry.get()
			
			text_widget.tag_remove("search_highlight", "1.0", tk.END)
			text_widget.tag_remove("current_search_highlight", "1.0", tk.END)
			viewer.search_matches = []
			viewer.current_match = -1
			
			if not search_term:
				search_result_label.config(text="0/0")
				return
			
			start_pos = "1.0"
			search_term_lower = search_term.lower()
			
			while True:
				pos = text_widget.search(search_term_lower, start_pos, stopindex=tk.END, nocase=True)
				if not pos:
					break
				
				end_pos = f"{pos}+{len(search_term)}c"
				viewer.search_matches.append(pos)
				text_widget.tag_add("search_highlight", pos, end_pos)
				start_pos = end_pos
			
			total_matches = len(viewer.search_matches)
			if total_matches > 0:
				viewer.current_match = 0
				highlight_current_match()
				search_result_label.config(text=f"1/{total_matches}")
			else:
				search_result_label.config(text="0/0")
		
		def highlight_current_match():
			if viewer.current_match >= 0 and viewer.current_match < len(viewer.search_matches):
				text_widget.tag_remove("current_search_highlight", "1.0", tk.END)
				
				pos = viewer.search_matches[viewer.current_match]
				search_term = search_entry.get()
				end_pos = f"{pos}+{len(search_term)}c"
				text_widget.tag_add("current_search_highlight", pos, end_pos)
				
				text_widget.see(pos)
				
				search_result_label.config(text=f"{viewer.current_match + 1}/{len(viewer.search_matches)}")
		
		def next_match():
			if len(viewer.search_matches) > 0:
				viewer.current_match = (viewer.current_match + 1) % len(viewer.search_matches)
				highlight_current_match()
		
		def prev_match():
			if len(viewer.search_matches) > 0:
				viewer.current_match = (viewer.current_match - 1) % len(viewer.search_matches)
				highlight_current_match()
		
		search_entry.bind("<Return>", perform_search)
		search_entry.bind("<KeyRelease>", perform_search)
		next_button.config(command=next_match)
		prev_button.config(command=prev_match)
		
		def apply_code_viewer_zoom():
			base_font_size = 10
			new_font_size = int(base_font_size * viewer.zoom_level)
			search_font_size = int(9 * viewer.zoom_level)
			text_widget.configure(font=("Consolas", new_font_size))
			line_numbers.configure(font=("Consolas", new_font_size))
			counter_label.configure(font=("Consolas", new_font_size, "bold"))
			search_label.configure(font=("Consolas", search_font_size))
			search_entry.configure(font=("Consolas", search_font_size))
			search_result_label.configure(font=("Consolas", search_font_size))
			prev_button.configure(font=("Consolas", search_font_size))
			next_button.configure(font=("Consolas", search_font_size))
			text_widget.config(state="normal")
			self._apply_python_syntax_highlighting(text_widget, code_content)
			text_widget.config(state="disabled")
			self.code_viewer_zoom = viewer.zoom_level
			self._save_config()
		
		def zoom_in_code_viewer():
			viewer.zoom_level = min(viewer.zoom_level + 0.1, 3.0)
			apply_code_viewer_zoom()
		
		def zoom_out_code_viewer():
			viewer.zoom_level = max(viewer.zoom_level - 0.1, 0.5)
			apply_code_viewer_zoom()
		
		def reset_zoom_code_viewer():
			viewer.zoom_level = 1.2
			apply_code_viewer_zoom()
		
		def handle_code_viewer_mouse_zoom(event):
			if event.delta > 0:
				zoom_in_code_viewer()
			else:
				zoom_out_code_viewer()
		
		viewer.bind("<Control-MouseWheel>", handle_code_viewer_mouse_zoom)
		viewer.bind("<Control-plus>", lambda e: zoom_in_code_viewer())
		viewer.bind("<Control-equal>", lambda e: zoom_in_code_viewer())
		viewer.bind("<Control-minus>", lambda e: zoom_out_code_viewer())
		viewer.bind("<Control-Key-0>", lambda e: reset_zoom_code_viewer())
	
	def _apply_python_syntax_highlighting(self, text_widget: tk.Text, code: str) -> None:
		color_scheme = {
			Token.Keyword: "#C586C0",              
			Token.Keyword.Constant: "#569CD6",     
			Token.Keyword.Namespace: "#C586C0",    
			Token.Name.Builtin: "#4EC9B0",         
			Token.Name.Builtin.Pseudo: "#569CD6",  
			Token.Name.Function: "#DCDCAA",        
			Token.Name.Class: "#4EC9B0",           
			Token.Name.Decorator: "#DCDCAA",       
			Token.String: "#CE9178",               
			Token.String.Doc: "#6A9955",           
			Token.Number: "#B5CEA8",               
			Token.Comment: "#6A9955",              
			Token.Comment.Single: "#6A9955",       
			Token.Comment.Multiline: "#6A9955",    
			Token.Operator: "#D4D4D4",             
			Token.Punctuation: "#D4D4D4",          
			Token.Name: "#9CDCFE",                 
		}
		
		text_widget.tag_config("highlight_open", background="#1F303A")   
		text_widget.tag_config("highlight_close", background="#1F3A1F")  
		
		current_font = text_widget.cget("font")
		if isinstance(current_font, str):
			parts = current_font.split()
			try:
				font_size = int(parts[-1])
			except (ValueError, IndexError):
				font_size = 10
		elif isinstance(current_font, tuple):
			font_size = current_font[1] if len(current_font) > 1 else 10
		else:
			font_size = 10
		
		for token_type, color in color_scheme.items():
			tag_name = str(token_type)
			if token_type in (Token.Comment, Token.Comment.Single, Token.Comment.Multiline):
				text_widget.tag_config(tag_name, foreground=color, font=("Consolas", font_size, "italic"))
			else:
				text_widget.tag_config(tag_name, foreground=color)
		
		lines = code.split('\n')
		for line_num, line in enumerate(lines, start=1):
			has_open = 'open(' in line
			has_close = '.close(' in line
			
			if has_open or has_close:
				start_idx = f"{line_num}.0"
				end_idx = f"{line_num}.end+1c"
				
				if has_open:
					text_widget.tag_add("highlight_open", start_idx, end_idx)
				if has_close:
					text_widget.tag_add("highlight_close", start_idx, end_idx)
		
		lexer = PythonLexer()
		tokens = lex(code, lexer)
		
		position = 0
		for token_type, token_value in tokens:
			token_length = len(token_value)
			if token_length > 0:
				start_idx = f"1.0+{position}c"
				end_idx = f"1.0+{position + token_length}c"
				
				tag_name = str(token_type)
				text_widget.tag_add(tag_name, start_idx, end_idx)
				
			position += token_length
		
		text_widget.tag_raise("highlight_open")
		text_widget.tag_raise("highlight_close")
	
	def _open_files_viewer(self) -> None:
		if self.submissions_dir is None:
			messagebox.showwarning("No Directory", "Please browse and select a directory first.")
			return
		
		if not DATA_DIR.exists() or not list(DATA_DIR.glob("*.txt")):
			messagebox.showwarning("No Data Files", "No stored data files found. Please add files in Settings.")
			return
		
		data_files_to_display = []
		for data_file in DATA_DIR.glob("*.txt"):
			target_file = self.submissions_dir / data_file.name
			if target_file.exists():
				data_files_to_display.append(target_file)
		data_files_to_display.sort(reverse=True)
		
		if not data_files_to_display:
			messagebox.showinfo("No Files", "No data files found in the selected directory.\nUse 'Reset Files' to copy them.")
			return
		
		viewer = tk.Toplevel(self.root)
		viewer.title("Data Files Viewer (Live)")
		
		screen_width = viewer.winfo_screenwidth()
		screen_height = viewer.winfo_screenheight()
		
		window_width = int(screen_width * 2 / 5)
		window_height = screen_height
		
		main_x = self.root.winfo_x()
		main_y = self.root.winfo_y()
		viewer.geometry(f"{window_width}x{window_height}+{main_x}+{main_y}")
		
		viewer.zoom_level = self.files_viewer_zoom
		viewer.text_widgets = []
		viewer.extra_line_positions = []  
		viewer.current_extra_line = -1
		
		top_nav_bar = tk.Frame(viewer, bg="#1E1E1E")
		top_nav_bar.pack(fill="x", padx=5, pady=(5, 0))
		
		nav_frame = tk.Frame(top_nav_bar, bg="#1E1E1E")
		nav_frame.pack(side="right", padx=5)
		
		initial_nav_font_size = int(9 * viewer.zoom_level)
		
		nav_label = tk.Label(nav_frame, text="Changed/New Lines:", bg="#1E1E1E", fg="#D4D4D4", 
							 font=("Consolas", initial_nav_font_size, "bold"))
		nav_label.pack(side="left", padx=(0, 5))
		
		extra_line_counter = tk.Label(nav_frame, text="0/0", bg="#1E1E1E", fg="#FF8C00", 
								  font=("Consolas", initial_nav_font_size, "bold"), width=8)
		extra_line_counter.pack(side="left", padx=(0, 5))
		
		prev_extra_button = tk.Button(nav_frame, text="◀", bg="#3C3C3C", fg="#D4D4D4", 
									  font=("Consolas", initial_nav_font_size), width=3, relief="solid", borderwidth=1)
		prev_extra_button.pack(side="left", padx=(0, 2))
		
		next_extra_button = tk.Button(nav_frame, text="▶", bg="#3C3C3C", fg="#D4D4D4", 
									  font=("Consolas", initial_nav_font_size), width=3, relief="solid", borderwidth=1)
		next_extra_button.pack(side="left")
		
		main_canvas = tk.Canvas(viewer)
		main_scrollbar = ttk.Scrollbar(viewer, orient="vertical", command=main_canvas.yview)
		scrollable_frame = ttk.Frame(main_canvas)
		
		scrollable_frame.bind(
			"<Configure>",
			lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
		)
		
		main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
		main_canvas.configure(yscrollcommand=main_scrollbar.set)
		
		main_canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
		main_scrollbar.pack(side="right", fill="y")
		
		def on_mousewheel(event):
			if not (event.state & 0x0004):  
				main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
		
		viewer.bind("<MouseWheel>", on_mousewheel)
		
		rainbow_colors = ["#DC143C", "#FF8C00", "#32CD32", "#FF1493", "#1E90FF", 
						  "#9370DB", "#FF1493", "#00CED1", "#FF4500", "#228B22"]
		
		file_viewers = {}
		
		for file_idx, file_path in enumerate(data_files_to_display):
			base_file_path = DATA_DIR / file_path.name
			text_widget = self._create_collapsible_csv_viewer(scrollable_frame, file_path, file_idx, rainbow_colors, base_file_path, viewer)
			if text_widget:
				file_viewers[str(file_path)] = text_widget
				viewer.text_widgets.append(text_widget)
		
		total_extra_lines = len(viewer.extra_line_positions)
		if total_extra_lines > 0:
			extra_line_counter.config(text=f"0/{total_extra_lines}")
		else:
			extra_line_counter.config(text="0/0")
		
		def navigate_to_extra_line():
			if viewer.current_extra_line >= 0 and viewer.current_extra_line < len(viewer.extra_line_positions):
				for text_widget in viewer.text_widgets:
					if text_widget.winfo_exists():
						text_widget.tag_remove("current_extra_line", "1.0", tk.END)
				
				text_widget, line_num = viewer.extra_line_positions[viewer.current_extra_line]
				
				text_widget.tag_add("current_extra_line", f"{line_num}.0", f"{line_num}.end+1c")
				text_widget.tag_raise("current_extra_line")
				
				text_widget.see(f"{line_num}.0")
				
				text_widget.update_idletasks()
				bbox = text_widget.bbox(f"{line_num}.0")
				if bbox:
					widget_y = text_widget.winfo_y()
					scroll_y = widget_y + bbox[1]
					canvas_height = main_canvas.winfo_height()
					scrollregion = main_canvas.cget("scrollregion").split()
					if scrollregion:
						total_height = float(scrollregion[3])
						if total_height > 0:
							fraction = scroll_y / total_height
							main_canvas.yview_moveto(max(0, min(1, fraction - 0.005)))
				
				extra_line_counter.config(text=f"{viewer.current_extra_line + 1}/{len(viewer.extra_line_positions)}")
		
		def next_extra_line():
			if len(viewer.extra_line_positions) > 0:
				viewer.current_extra_line = (viewer.current_extra_line + 1) % len(viewer.extra_line_positions)
				navigate_to_extra_line()
		
		def prev_extra_line():
			if len(viewer.extra_line_positions) > 0:
				viewer.current_extra_line = (viewer.current_extra_line - 1) % len(viewer.extra_line_positions)
				navigate_to_extra_line()
		
		next_extra_button.config(command=next_extra_line)
		prev_extra_button.config(command=prev_extra_line)
		
		def apply_files_viewer_zoom():
			base_font_size = 11
			new_font_size = int(base_font_size * viewer.zoom_level)
			nav_font_size = int(9 * viewer.zoom_level)
			for text_widget in viewer.text_widgets:
				if text_widget.winfo_exists():
					text_widget.configure(font=("Consolas", new_font_size, "bold"))
					for i in range(len(rainbow_colors)):
						text_widget.tag_config(f"col{i}", foreground=rainbow_colors[i], font=("Consolas", new_font_size, "bold"))
			nav_label.configure(font=("Consolas", nav_font_size, "bold"))
			extra_line_counter.configure(font=("Consolas", nav_font_size, "bold"))
			prev_extra_button.configure(font=("Consolas", nav_font_size))
			next_extra_button.configure(font=("Consolas", nav_font_size))
			self.files_viewer_zoom = viewer.zoom_level
			self._save_config()
		
		def zoom_in_files_viewer():
			viewer.zoom_level = min(viewer.zoom_level + 0.1, 3.0)
			apply_files_viewer_zoom()
		
		def zoom_out_files_viewer():
			viewer.zoom_level = max(viewer.zoom_level - 0.1, 0.5)
			apply_files_viewer_zoom()
		
		def reset_zoom_files_viewer():
			viewer.zoom_level = 1.2
			apply_files_viewer_zoom()
		
		def handle_files_viewer_mouse_zoom(event):
			if event.delta > 0:
				zoom_in_files_viewer()
			else:
				zoom_out_files_viewer()
		
		viewer.bind("<Control-MouseWheel>", handle_files_viewer_mouse_zoom)
		viewer.bind("<Control-plus>", lambda e: zoom_in_files_viewer())
		viewer.bind("<Control-equal>", lambda e: zoom_in_files_viewer())
		viewer.bind("<Control-minus>", lambda e: zoom_out_files_viewer())
		viewer.bind("<Control-Key-0>", lambda e: reset_zoom_files_viewer())
		
		class FileChangeHandler(FileSystemEventHandler):
			def __init__(self, viewer_window, file_viewers_dict, colors, counter_label):
				self.viewer_window = viewer_window
				self.file_viewers = file_viewers_dict
				self.colors = colors
				self.counter_label = counter_label
			
			def on_modified(self, event):
				if event.is_directory:
					return
				
				file_path = Path(event.src_path)
				if file_path.suffix == '.txt' and str(file_path) in self.file_viewers:
					self.viewer_window.after(100, lambda: self._update_file_content(file_path))
			
			def _update_file_content(self, file_path):
				if str(file_path) not in self.file_viewers:
					return
				
				text_widget = self.file_viewers[str(file_path)]
				if not text_widget.winfo_exists():
					return
				
				try:
					content = file_path.read_text(encoding="utf-8")
					lines = content.strip().split('\n')
					
					base_file_path = DATA_DIR / file_path.name
					base_lines = []
					if base_file_path.exists():
						try:
							base_content = base_file_path.read_text(encoding="utf-8")
							base_lines = base_content.strip().split('\n')
						except Exception:
							pass
					
					first_line = lines[0] if lines else ""
					delimiter = ',' if ',' in first_line else '\t'
					
					text_widget.config(state="normal")
					text_widget.delete("1.0", tk.END)
					
					self.viewer_window.extra_line_positions = [
						(widget, line) for widget, line in self.viewer_window.extra_line_positions 
						if widget != text_widget
					]
					
					for line_idx, line in enumerate(lines):
						line_num = line_idx + 1
						
						is_extra = line_idx >= len(base_lines)
						is_modified = False
						
						if not is_extra and line_idx < len(base_lines):
							if line.strip() != base_lines[line_idx].strip():
								is_modified = True
						
						columns = line.split(delimiter)
						for col_idx, column in enumerate(columns):
							color_idx = col_idx % len(self.colors)
							text_widget.insert("end", column, f"col{color_idx}")
							if col_idx < len(columns) - 1:
								text_widget.insert("end", delimiter)
						text_widget.insert("end", "\n")
						
						if is_extra:
							text_widget.tag_add("extra_line", f"{line_num}.0", f"{line_num}.end")
							self.viewer_window.extra_line_positions.append((text_widget, line_num))
						elif is_modified:
							text_widget.tag_add("modified_line", f"{line_num}.0", f"{line_num}.end")
							self.viewer_window.extra_line_positions.append((text_widget, line_num))
					
					total_extra = len(self.viewer_window.extra_line_positions)
					if self.viewer_window.current_extra_line >= total_extra:
						self.viewer_window.current_extra_line = -1
					
					if total_extra > 0:
						if self.viewer_window.current_extra_line == -1:
							self.counter_label.config(text=f"0/{total_extra}")
						else:
							self.counter_label.config(text=f"{self.viewer_window.current_extra_line + 1}/{total_extra}")
					else:
						self.counter_label.config(text="0/0")
					
					text_widget.config(height=len(lines), state="disabled")
				except Exception as e:
					print(f"Error updating {file_path}: {e}")
		
		event_handler = FileChangeHandler(viewer, file_viewers, rainbow_colors, extra_line_counter)
		observer = Observer()
		observer.schedule(event_handler, str(self.submissions_dir), recursive=False)
		observer.start()
		
		def on_viewer_close():
			viewer.unbind("<MouseWheel>")
			observer.stop()
			observer.join()
			viewer.destroy()
		
		viewer.protocol("WM_DELETE_WINDOW", on_viewer_close)
	
	def _create_collapsible_csv_viewer(self, parent: ttk.Frame, file_path: Path, idx: int, colors: list, base_file_path: Path = None, viewer_window = None) -> tk.Text | None:
		file_frame = ttk.LabelFrame(parent, text=file_path.name, padding=5)
		file_frame.pack(fill="both", expand=True, padx=5, pady=5)
		
		is_collapsed = tk.BooleanVar(value=False)
		
		header_frame = ttk.Frame(file_frame)
		header_frame.pack(fill="x")
		
		toggle_button = ttk.Button(header_frame, text="▼ Collapse", width=12)
		toggle_button.pack(side="left", padx=5, pady=2)
		
		content_frame = ttk.Frame(file_frame)
		content_frame.pack(fill="both", expand=True, pady=(5, 0))
		
		try:
			content = file_path.read_text(encoding="utf-8")
		except Exception as e:
			error_label = ttk.Label(content_frame, text=f"Error reading file: {e}", foreground="red")
			error_label.pack()
			return None
		
		lines = content.strip().split('\n')
		num_lines = len(lines)
		
		base_lines = []
		if base_file_path and base_file_path.exists():
			try:
				base_content = base_file_path.read_text(encoding="utf-8")
				base_lines = base_content.strip().split('\n')
			except Exception:
				pass
		
		initial_font_size = int(11 * self.files_viewer_zoom)
		
		text_widget = tk.Text(content_frame, wrap="none",
							  font=("Consolas", initial_font_size, "bold"),
							  bg="white",
							  borderwidth=2,
							  relief="solid",
							  padx=10,
							  pady=10)
		text_widget.pack(fill="both", expand=False, padx=5, pady=5)
		
		text_widget.tag_config("extra_line", background="#FFFF99")  # Yellow - new lines at end
		text_widget.tag_config("modified_line", background="#FFD4A3")  # Light orange - modified content
		text_widget.tag_config("current_extra_line", background="#FFA500")  # Orange - currently selected
		
		if lines:
			first_line = lines[0]
			delimiter = ',' if ',' in first_line else '\t'
			
			for i, color in enumerate(colors):
				text_widget.tag_config(f"col{i}", foreground=color, font=("Consolas", initial_font_size, "bold"))
			
			for line_idx, line in enumerate(lines):
				line_num = line_idx + 1
				
				is_extra = line_idx >= len(base_lines)
				is_modified = False
				
				if not is_extra and line_idx < len(base_lines):
					if line.strip() != base_lines[line_idx].strip():
						is_modified = True
				
				columns = line.split(delimiter)
				for col_idx, column in enumerate(columns):
					color_idx = col_idx % len(colors)
					text_widget.insert("end", column, f"col{color_idx}")
					if col_idx < len(columns) - 1:
						text_widget.insert("end", delimiter)
				text_widget.insert("end", "\n")
				
				if is_extra:
					text_widget.tag_add("extra_line", f"{line_num}.0", f"{line_num}.end")
					if viewer_window:
						viewer_window.extra_line_positions.append((text_widget, line_num))
				elif is_modified:
					text_widget.tag_add("modified_line", f"{line_num}.0", f"{line_num}.end")
					if viewer_window:
						viewer_window.extra_line_positions.append((text_widget, line_num))
		
		text_widget.config(height=num_lines, state="disabled")
		
		def toggle_collapse():
			if is_collapsed.get():
				content_frame.pack(fill="both", expand=True, pady=(5, 0))
				toggle_button.config(text="▼ Collapse")
				is_collapsed.set(False)
			else:
				content_frame.pack_forget()
				toggle_button.config(text="▶ Expand")
				is_collapsed.set(True)
		
		toggle_button.config(command=toggle_collapse)
		
		return text_widget

	def _save_predefined_inputs(self) -> None:
		PREDEFINED_INPUTS_PATH.write_text(json.dumps(self.predefined_inputs, indent=2), encoding="utf-8")

	def _reload_predefined_listbox(self) -> None:
		self.predefined_listbox.delete(0, tk.END)
		for i, item in enumerate(self.predefined_inputs):
			self.predefined_listbox.insert(tk.END, item)
			if item.strip().startswith("#"):
				self.predefined_listbox.itemconfig(i, fg="blue", selectbackground="lightblue")
			if item.strip().startswith("# Checklist "):
				self.predefined_listbox.itemconfig(i, fg="green", selectbackground="lightblue")

	def _on_process_end(self) -> None:
		if self.process:
			if self.process.stdin:
				self.process.stdin.close()
			if self.process.stdout:
				self.process.stdout.close()
		self.process = None
		self.output_thread = None
		self.run_button.configure(state="normal", bg="#90EE90", activebackground="#7CCD7C")
		self.stop_button.configure(state="disabled", bg=self.root.cget('bg'))

	def _on_close(self) -> None:
		if self.process and self.process.poll() is None:
			if not messagebox.askyesno("Exit", "A process is still running. Stop it and exit?"):
				return
			self._stop_process()

		self.root.destroy()

	def _setup_zoom_bindings(self) -> None:
		self.root.bind("<Control-MouseWheel>", self._handle_mouse_zoom)
		self.root.bind("<Control-plus>", lambda e: self._zoom_in())
		self.root.bind("<Control-equal>", lambda e: self._zoom_in())  # Ctrl+= (same key as +)
		self.root.bind("<Control-minus>", lambda e: self._zoom_out())
		self.root.bind("<Control-Key-0>", lambda e: self._reset_zoom())

	def _handle_mouse_zoom(self, event: tk.Event) -> None:
		if event.delta > 0:
			self._zoom_in()
		else:
			self._zoom_out()

	def _zoom_in(self) -> None:
		self.zoom_level = min(self.zoom_level + 0.1, 3.0)
		self._apply_zoom()
		self._save_config()

	def _zoom_out(self) -> None:
		self.zoom_level = max(self.zoom_level - 0.1, 0.5)
		self._apply_zoom()
		self._save_config()

	def _reset_zoom(self) -> None:
		self.zoom_level = 1.0
		self._apply_zoom()
		self._save_config()

	def _apply_zoom(self) -> None:
		base_font_size = 9
		new_font_size = int(base_font_size * self.zoom_level)
		
		style = ttk.Style()
		style.configure(".", font=("TkDefaultFont", new_font_size))
		
		text_font_size = int(10 * self.zoom_level)
		self.output_text.configure(font=("Consolas", text_font_size))
		
		if self.feedback_text:
			self.feedback_text.configure(font=("TkDefaultFont", new_font_size))
		
		entry_font = ("TkDefaultFont", new_font_size)
		self.file_combo.configure(font=entry_font)
		self.manual_entry.configure(font=entry_font)
		self.points_adjust_entry.configure(font=entry_font)
		
		listbox_font = ("TkDefaultFont", new_font_size)
		self.predefined_listbox.configure(font=listbox_font)
		
		points_font_size = int(10 * self.zoom_level)
		self.points_display.configure(font=("TkDefaultFont", points_font_size, "bold"))
		self.grade_display.configure(font=("TkDefaultFont", points_font_size, "bold"))
		
		label_font = ("TkDefaultFont", int(8 * self.zoom_level))
		self.directory_label.configure(font=label_font)
		
		button_font = ("TkDefaultFont", new_font_size)
		self.run_button.configure(font=button_font)
		self.stop_button.configure(font=button_font)
		self.clear_button.configure(font=button_font)
		self.open_code_button.configure(font=button_font)
		self.open_files_button.configure(font=button_font)
		
		menu_font = ("Segoe UI", new_font_size)
		try:
			self.menubar.config(font=menu_font)
			self.file_menu.config(font=menu_font)
			self.view_menu.config(font=menu_font)
		except Exception:
			pass

	def _load_config(self) -> None:
		if CONFIG_PATH.exists():
			try:
				config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
				if isinstance(config, dict):
					if "zoom_level" in config:
						self.zoom_level = max(0.5, min(3.0, float(config["zoom_level"])))
					if "submissions_dir" in config:
						loaded_dir = Path(config["submissions_dir"])
						if loaded_dir.exists():
							self.submissions_dir = loaded_dir
					if "last_opened_file" in config:
						self.last_opened_file = config["last_opened_file"]
					if "current_points" in config:
						self.current_points = max(0, min(100, int(float(config["current_points"]))))
					if "last_file_for_points" in config:
						self.last_file_for_points = config["last_file_for_points"]
					if "code_viewer_zoom" in config:
						self.code_viewer_zoom = max(0.5, min(3.0, float(config["code_viewer_zoom"])))
					if "files_viewer_zoom" in config:
						self.files_viewer_zoom = max(0.5, min(3.0, float(config["files_viewer_zoom"])))
			except (json.JSONDecodeError, ValueError, KeyError):
				self.zoom_level = 1.0

	def _save_config(self) -> None:
		config = {
			"zoom_level": self.zoom_level,
			"current_points": self.current_points,
			"last_file_for_points": self.last_file_for_points,
			"code_viewer_zoom": self.code_viewer_zoom,
			"files_viewer_zoom": self.files_viewer_zoom
		}
		if self.submissions_dir is not None:
			config["submissions_dir"] = str(self.submissions_dir)
		if hasattr(self, 'last_opened_file'):
			config["last_opened_file"] = self.last_opened_file
		CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def initialize_bundled_resources():
	if not getattr(sys, 'frozen', False):
		return  
		
	bundled_data = get_resource_path("data")
	if bundled_data.exists() and not DATA_DIR.exists():
		shutil.copytree(bundled_data, DATA_DIR)
	
	bundled_config = get_resource_path("config.json")
	if bundled_config.exists() and not CONFIG_PATH.exists():
		shutil.copy(bundled_config, CONFIG_PATH)
	
	bundled_inputs = get_resource_path("predefined_inputs.json")
	if bundled_inputs.exists() and not PREDEFINED_INPUTS_PATH.exists():
		shutil.copy(bundled_inputs, PREDEFINED_INPUTS_PATH)
	
	bundled_feedback = get_resource_path("feedback_template.txt")
	if bundled_feedback.exists() and not FEEDBACK_TEMPLATE_PATH.exists():
		shutil.copy(bundled_feedback, FEEDBACK_TEMPLATE_PATH)

def main() -> None:
	initialize_bundled_resources()
	
	if not DATA_DIR.exists():
		DATA_DIR.mkdir(parents=True, exist_ok=True)

	root = tk.Tk()
	PythonTesterApp(root)
	root.mainloop()

if __name__ == "__main__":
	main()
