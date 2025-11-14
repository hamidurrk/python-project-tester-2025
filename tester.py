import json
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from pygments import lex
from pygments.lexers import PythonLexer
from pygments.token import Token

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PREDEFINED_INPUTS_PATH = BASE_DIR / "predefined_inputs.json"
CONFIG_PATH = BASE_DIR / "config.json"

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

class PythonTesterApp:
	def __init__(self, root: tk.Tk) -> None:
		self.root = root
		self.root.title("Project Tester")

		self.process: subprocess.Popen | None = None
		self.output_queue: queue.Queue[str] = queue.Queue()
		self.output_thread: threading.Thread | None = None

		self.file_var = tk.StringVar()
		self.predefined_inputs: list[str] = []
		self.zoom_level = 1.0
		self.submissions_dir: Path | None = None
		self.current_points = 100
		self.last_file_for_points = None

		self._load_config()
		self._create_menu()
		self._build_layout()
		self._load_predefined_inputs()
		self._refresh_file_list()
		self._poll_output_queue()
		self._setup_zoom_bindings()
		self._apply_zoom()  
		self._update_points_display() 
		self.root.protocol("WM_DELETE_WINDOW", self._on_close)

	def _create_menu(self) -> None:
		self.menubar = tk.Menu(self.root)
		self.root.config(menu=self.menubar)

		self.file_menu = tk.Menu(self.menubar, tearoff=0)
		self.menubar.add_cascade(label="File", menu=self.file_menu)
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
		self.root.rowconfigure(0, weight=0)  # Point tracker row
		self.root.rowconfigure(1, weight=1)  # Main content row

		main_frame = ttk.Frame(self.root, padding=12)
		main_frame.grid(row=0, column=0, rowspan=2, sticky="nsew")
		main_frame.columnconfigure(0, weight=1)
		main_frame.rowconfigure(3, weight=1)

		ttk.Label(main_frame, text="Submission File").grid(row=0, column=0, sticky="w")

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
									 relief="raised", cursor="hand2")
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
		points_grade_frame.columnconfigure(1, weight=1)  
		
		self.points_display = ttk.Label(points_grade_frame, text="100.0", font=("TkDefaultFont", 8, "bold"), foreground="green")
		self.points_display.grid(row=0, column=0, sticky="w")
		
		grade_container = ttk.Frame(points_grade_frame)
		grade_container.grid(row=0, column=1, sticky="e", padx=(8, 0))
		
		ttk.Label(grade_container, text="Grade: ").grid(row=0, column=0, sticky="e")
		
		self.grade_display = ttk.Label(grade_container, text="5", font=("TkDefaultFont", 8, "bold"), foreground="green")
		self.grade_display.grid(row=0, column=1, sticky="e")

		ttk.Label(points_frame, text="Adjust Points:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
		
		adjust_row = ttk.Frame(points_frame)
		adjust_row.grid(row=1, column=1, sticky="ew", pady=(6, 0))
		adjust_row.columnconfigure(0, weight=1)

		self.points_adjust_var = tk.StringVar(value="-4")
		self.points_adjust_entry = ttk.Entry(adjust_row, textvariable=self.points_adjust_var, width=8)
		self.points_adjust_entry.grid(row=0, column=0, sticky="w", padx=(0, 6))
		self.points_adjust_entry.bind("<Return>", lambda e: self._adjust_points())

		apply_button = ttk.Button(adjust_row, text="Apply", command=self._adjust_points, width=8)
		apply_button.grid(row=0, column=1)

		reset_button = ttk.Button(adjust_row, text="Reset", command=self._reset_points, width=8)
		reset_button.grid(row=0, column=2, padx=(6, 0))

		sidebar = ttk.LabelFrame(self.root, text="Predefined Inputs", padding=12)
		sidebar.grid(row=1, column=1, sticky="nsew", padx=(0, 12), pady=(6, 12))
		sidebar.columnconfigure(0, weight=1)
		sidebar.rowconfigure(1, weight=1)

		label_row = ttk.Frame(sidebar)
		label_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
		label_row.columnconfigure(0, weight=1)

		ttk.Label(label_row, text="Press Enter or Space to send\nDouble click to edit").grid(row=0, column=0, sticky="w")

		move_up_button = ttk.Button(label_row, text="↑", width=3, command=self._move_predefined_up)
		move_up_button.grid(row=0, column=1, padx=(6, 3))

		move_down_button = ttk.Button(label_row, text="↓", width=3, command=self._move_predefined_down)
		move_down_button.grid(row=0, column=2)

		self.predefined_listbox = tk.Listbox(sidebar, height=15)
		self.predefined_listbox.grid(row=1, column=0, sticky="nsew", pady=(6, 6))
		self.predefined_listbox.bind("<Double-Button-1>", self._handle_predefined_double_click)
		self.predefined_listbox.bind("<Return>", lambda e: self._send_selected_predefined())
		self.predefined_listbox.bind("<space>", lambda e: self._handle_space_key())
		self.predefined_listbox.bind("<Control-e>", lambda e: self._edit_selected_predefined())
		self.predefined_listbox.bind("<Button-3>", self._show_context_menu)
		
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

		ttk.Label(sidebar, text="Add New Input (# for labels)").grid(row=3, column=0, sticky="w")

		add_row = ttk.Frame(sidebar)
		add_row.grid(row=4, column=0, sticky="ew")
		add_row.columnconfigure(0, weight=1)

		self.new_input_var = tk.StringVar()
		self.new_input_entry = ttk.Entry(add_row, textvariable=self.new_input_var)
		self.new_input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
		self.new_input_entry.bind("<Return>", lambda e: self._add_new_predefined())

		add_button = ttk.Button(add_row, text="Add", command=self._add_new_predefined)
		add_button.grid(row=0, column=1)

	def _refresh_file_list(self) -> None:
		if self.submissions_dir is None:
			self.file_combo["values"] = []
			if self.file_var.get():
				self.file_var.set("")
			return
		
		if not self.submissions_dir.exists():
			messagebox.showwarning("Directory Missing", 
				f"The directory {self.submissions_dir} no longer exists.\nPlease browse for a new directory.")
			self.submissions_dir = None
			self._save_config()
			self.file_combo["values"] = []
			if self.file_var.get():
				self.file_var.set("")
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
			self.process = subprocess.Popen(
				[sys.executable, str(script_path)],
				cwd=str(script_path.parent),
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.STDOUT,
				text=True,
				bufsize=1,
			)
		except OSError as err:
			messagebox.showerror("Execution Error", f"Failed to start process: {err}")
			return

		self._clear_terminal()
		self._append_output(f"Running {selected_file}...\n")

		self.run_button.configure(state="disabled")
		self.stop_button.configure(state="normal")

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
		for line in self.process.stdout:
			self.output_queue.put(line)

		return_code = self.process.wait()
		self.output_queue.put(f"\nProcess exited with code {return_code}.\n")
		self.output_queue.put(None)  # Sentinel to mark completion.

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
			value = self.predefined_listbox.get(current_index)
			
			if not value.strip().startswith("#"):
				self._send_to_process(value)
			
			next_index = current_index + 1
			if next_index < self.predefined_listbox.size():
				self.predefined_listbox.selection_clear(0, tk.END)
				self.predefined_listbox.selection_set(next_index)
				self.predefined_listbox.see(next_index)

	def _handle_predefined_double_click(self, event: tk.Event) -> None:
		"""Handle double-click to edit the item inline"""
		self._edit_selected_predefined()

	def _edit_selected_predefined(self) -> None:
		"""Start inline editing of the selected predefined input"""
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
		
		self.edit_entry = tk.Entry(self.predefined_listbox)
		self.edit_entry.insert(0, current_value)
		self.edit_entry.select_range(0, tk.END)
		self.edit_entry.place(x=0, y=y, width=listbox_width, height=height)
		self.edit_entry.focus_set()
		
		self.edit_entry.bind("<Return>", lambda e: self._finish_edit())
		self.edit_entry.bind("<Escape>", lambda e: self._cancel_edit())
		self.edit_entry.bind("<FocusOut>", lambda e: self._finish_edit())

	def _finish_edit(self) -> None:
		"""Finish editing and save the changes"""
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

	def _cancel_edit(self) -> None:
		"""Cancel editing without saving changes"""
		if not self.edit_entry:
			return
		
		self.edit_entry.destroy()
		self.edit_entry = None
		self.edit_index = None

	def _handle_space_key(self) -> None:
		"""Handle spacebar press - send input and move to next, preventing default toggle behavior"""
		self._send_selected_predefined()
		return "break"  # Prevent default spacebar behavior

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

	def _add_new_predefined(self) -> None:
		new_value = self.new_input_var.get()
		self.predefined_inputs.append(new_value)
		self._save_predefined_inputs()
		self._reload_predefined_listbox()
		self.new_input_var.set("")
		
		last_index = len(self.predefined_inputs) - 1
		self.predefined_listbox.see(last_index)

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
			adjustment = float(adjustment_str)
			
			self.current_points += adjustment
			self.current_points = max(0, min(100, self.current_points))
			
			self._update_points_display()
			self._save_config()
		except ValueError:
			messagebox.showerror("Invalid Input", "Please enter a valid number (e.g., -4, +5, or 3)")

	def _reset_points(self) -> None:
		"""Reset points to 100"""
		self.current_points = 100
		self.points_adjust_var.set("-4")
		self._update_points_display()
		self._save_config()

	def _update_points_display(self) -> None:
		grade = self._calculate_grade(self.current_points)
		color = GRADE_COLORS[grade]
		
		self.points_display.config(text=f"{self.current_points:.1f}", foreground=color)
		
		self.grade_display.config(text=grade, foreground=color)
	
	def _calculate_grade(self, points: float) -> str:
		"""Calculate the grade based on points."""
		for grade, (min_points, max_points) in GRADE_SCALE.items():
			if min_points <= points <= max_points:
				return grade
		return "F" 

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

		self._reload_predefined_listbox()

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

	def _open_settings(self) -> None:
		settings_window = tk.Toplevel(self.root)
		settings_window.title("Settings")
		settings_window.geometry("500x400")
		settings_window.transient(self.root)
		settings_window.grab_set()
		
		general_frame = ttk.LabelFrame(settings_window, text="General", padding=10)
		general_frame.pack(fill="both", expand=True, padx=10, pady=10)
		
		label = ttk.Label(general_frame, text="Stored Data Files (.txt):")
		label.pack(anchor="w", pady=(0, 5))
		
		list_frame = ttk.Frame(general_frame)
		list_frame.pack(fill="both", expand=True, pady=(0, 10))
		
		scrollbar = ttk.Scrollbar(list_frame)
		scrollbar.pack(side="right", fill="y")
		
		data_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set)
		data_listbox.pack(side="left", fill="both", expand=True)
		scrollbar.config(command=data_listbox.yview)
		
		def refresh_data_files():
			data_listbox.delete(0, tk.END)
			if DATA_DIR.exists():
				for file in sorted(DATA_DIR.glob("*.txt")):
					data_listbox.insert(tk.END, file.name)
		
		refresh_data_files()
		
		buttons_frame = ttk.Frame(general_frame)
		buttons_frame.pack(fill="x")
		
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
					# messagebox.showinfo("Success", f"Added {source.name} to data files.")
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
					# messagebox.showinfo("Success", f"Removed {filename} from data files.")
				except Exception as e:
					messagebox.showerror("Error", f"Failed to remove file: {e}")
		
		add_button = ttk.Button(buttons_frame, text="Add File", command=add_data_file)
		add_button.pack(side="left", padx=(0, 5))
		
		remove_button = ttk.Button(buttons_frame, text="Remove File", command=remove_data_file)
		remove_button.pack(side="left")
		
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
		viewer.geometry("800x600")
		viewer.configure(bg="#1E1E1E")  
		
		frame = tk.Frame(viewer, bg="#1E1E1E")
		frame.pack(fill="both", expand=True, padx=5, pady=5)
		
		text_frame = tk.Frame(frame, bg="#1E1E1E")
		text_frame.pack(fill="both", expand=True)
		
		v_scrollbar = tk.Scrollbar(text_frame, bg="#252526", troughcolor="#1E1E1E")
		v_scrollbar.pack(side="right", fill="y")
		
		h_scrollbar = tk.Scrollbar(frame, orient="horizontal", bg="#252526", troughcolor="#1E1E1E")
		h_scrollbar.pack(side="bottom", fill="x")
		
		line_numbers = tk.Text(text_frame, wrap="none",
							   width=5,
							   font=("Consolas", 10),
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
							  font=("Consolas", 10),
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
	
	def _apply_python_syntax_highlighting(self, text_widget: tk.Text, code: str) -> None:
		"""Apply syntax highlighting using Pygments with VS Code Dark+ theme colors."""
		
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
		
		for token_type, color in color_scheme.items():
			tag_name = str(token_type)
			if token_type in (Token.Comment, Token.Comment.Single, Token.Comment.Multiline):
				text_widget.tag_config(tag_name, foreground=color, font=("Consolas", 10, "italic"))
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
		viewer.geometry("900x700")
		
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
			main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
		
		viewer.bind("<MouseWheel>", on_mousewheel)
		
		rainbow_colors = ["#DC143C", "#FF8C00", "#32CD32", "#FF1493", "#1E90FF", 
						  "#9370DB", "#FF1493", "#00CED1", "#FF4500", "#228B22"]
		
		file_viewers = {}
		
		for file_idx, file_path in enumerate(data_files_to_display):
			text_widget = self._create_collapsible_csv_viewer(scrollable_frame, file_path, file_idx, rainbow_colors)
			if text_widget:
				file_viewers[str(file_path)] = text_widget
		
		class FileChangeHandler(FileSystemEventHandler):
			def __init__(self, viewer_window, file_viewers_dict, colors):
				self.viewer_window = viewer_window
				self.file_viewers = file_viewers_dict
				self.colors = colors
			
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
					
					first_line = lines[0] if lines else ""
					delimiter = ',' if ',' in first_line else '\t'
					
					text_widget.config(state="normal")
					text_widget.delete("1.0", tk.END)
					
					for line in lines:
						columns = line.split(delimiter)
						for col_idx, column in enumerate(columns):
							color_idx = col_idx % len(self.colors)
							text_widget.insert("end", column, f"col{color_idx}")
							if col_idx < len(columns) - 1:
								text_widget.insert("end", delimiter)
						text_widget.insert("end", "\n")
					
					text_widget.config(height=len(lines), state="disabled")
				except Exception as e:
					print(f"Error updating {file_path}: {e}")
		
		event_handler = FileChangeHandler(viewer, file_viewers, rainbow_colors)
		observer = Observer()
		observer.schedule(event_handler, str(self.submissions_dir), recursive=False)
		observer.start()
		
		def on_viewer_close():
			viewer.unbind("<MouseWheel>")
			observer.stop()
			observer.join()
			viewer.destroy()
		
		viewer.protocol("WM_DELETE_WINDOW", on_viewer_close)
	
	def _create_collapsible_csv_viewer(self, parent: ttk.Frame, file_path: Path, idx: int, colors: list) -> tk.Text | None:
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
		
		text_widget = tk.Text(content_frame, wrap="none",
							  font=("Consolas", 11, "bold"),
							  bg="white",
							  borderwidth=2,
							  relief="solid",
							  padx=10,
							  pady=10)
		text_widget.pack(fill="both", expand=False, padx=5, pady=5)
		
		if lines:
			first_line = lines[0]
			delimiter = ',' if ',' in first_line else '\t'
			
			for i, color in enumerate(colors):
				text_widget.tag_config(f"col{i}", foreground=color, font=("Consolas", 11, "bold"))
			
			for line in lines:
				columns = line.split(delimiter)
				for col_idx, column in enumerate(columns):
					color_idx = col_idx % len(colors)
					text_widget.insert("end", column, f"col{color_idx}")
					if col_idx < len(columns) - 1:
						text_widget.insert("end", delimiter)
				text_widget.insert("end", "\n")
		
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

	def _on_process_end(self) -> None:
		if self.process:
			if self.process.stdin:
				self.process.stdin.close()
			if self.process.stdout:
				self.process.stdout.close()
		self.process = None
		self.output_thread = None
		self.run_button.configure(state="normal")
		self.stop_button.configure(state="disabled")

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
		self.output_text.configure(font=("TkFixedFont", text_font_size))
		
		entry_font = ("TkDefaultFont", new_font_size)
		self.file_combo.configure(font=entry_font)
		self.manual_entry.configure(font=entry_font)
		self.new_input_entry.configure(font=entry_font)
		self.points_adjust_entry.configure(font=entry_font)
		
		listbox_font = ("TkDefaultFont", new_font_size)
		self.predefined_listbox.configure(font=listbox_font)
		
		points_font_size = int(10 * self.zoom_level)
		self.points_display.configure(font=("TkDefaultFont", points_font_size, "bold"))
		self.grade_display.configure(font=("TkDefaultFont", points_font_size, "bold"))
		
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
						self.current_points = max(0, min(100, float(config["current_points"])))
					if "last_file_for_points" in config:
						self.last_file_for_points = config["last_file_for_points"]
			except (json.JSONDecodeError, ValueError, KeyError):
				self.zoom_level = 1.0

	def _save_config(self) -> None:
		config = {
			"zoom_level": self.zoom_level,
			"current_points": self.current_points,
			"last_file_for_points": self.last_file_for_points
		}
		if self.submissions_dir is not None:
			config["submissions_dir"] = str(self.submissions_dir)
		if hasattr(self, 'last_opened_file'):
			config["last_opened_file"] = self.last_opened_file
		CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def main() -> None:
	if not DATA_DIR.exists():
		DATA_DIR.mkdir(parents=True, exist_ok=True)

	root = tk.Tk()
	PythonTesterApp(root)
	root.mainloop()


if __name__ == "__main__":
	main()
