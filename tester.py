import json
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

BASE_DIR = Path(__file__).resolve().parent
SUBMISSIONS_DIR = BASE_DIR / "submissions"
PREDEFINED_INPUTS_PATH = BASE_DIR / "predefined_inputs.json"
CONFIG_PATH = BASE_DIR / "config.json"

class PythonTesterApp:
	def __init__(self, root: tk.Tk) -> None:
		self.root = root
		self.root.title("Submission Runner")

		self.process: subprocess.Popen | None = None
		self.output_queue: queue.Queue[str] = queue.Queue()
		self.output_thread: threading.Thread | None = None

		self.file_var = tk.StringVar()
		self.predefined_inputs: list[str] = []
		self.zoom_level = 1.0
		self.submissions_dir = SUBMISSIONS_DIR

		self._load_config()
		self._create_menu()
		self._build_layout()
		self._load_predefined_inputs()
		self._refresh_file_list()
		self._poll_output_queue()
		self._setup_zoom_bindings()
		self._apply_zoom()  # Apply loaded zoom level

		self.root.protocol("WM_DELETE_WINDOW", self._on_close)

	def _create_menu(self) -> None:
		self.menubar = tk.Menu(self.root)
		self.root.config(menu=self.menubar)

		# File menu
		self.file_menu = tk.Menu(self.menubar, tearoff=0)
		self.menubar.add_cascade(label="File", menu=self.file_menu)
		self.file_menu.add_command(label="Import Predefined Inputs", command=self._import_predefined_inputs)
		self.file_menu.add_command(label="Export Predefined Inputs", command=self._export_predefined_inputs)
		self.file_menu.add_separator()
		self.file_menu.add_command(label="Exit", command=self._on_close)

		# View menu
		self.view_menu = tk.Menu(self.menubar, tearoff=0)
		self.menubar.add_cascade(label="View", menu=self.view_menu)
		self.view_menu.add_command(label="Zoom In", command=self._zoom_in, accelerator="Ctrl++")
		self.view_menu.add_command(label="Zoom Out", command=self._zoom_out, accelerator="Ctrl+-")
		self.view_menu.add_command(label="Reset Zoom", command=self._reset_zoom, accelerator="Ctrl+0")

	def _build_layout(self) -> None:
		self.root.columnconfigure(0, weight=3)
		self.root.columnconfigure(1, weight=2)
		self.root.rowconfigure(0, weight=1)

		main_frame = ttk.Frame(self.root, padding=12)
		main_frame.grid(row=0, column=0, sticky="nsew")
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
		browse_button.grid(row=0, column=2)

		controls = ttk.Frame(main_frame)
		controls.grid(row=2, column=0, sticky="ew", pady=(0, 8))
		controls.columnconfigure((0, 1, 2), weight=1)

		self.run_button = tk.Button(controls, text="▶ Run", command=self._run_selected_file, 
									 relief="raised", cursor="hand2")
		self.run_button.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=2)

		self.stop_button = tk.Button(controls, text="■ Stop", command=self._stop_process, 
									  relief="raised", cursor="hand2", state="disabled")
		self.stop_button.grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=2)

		self.clear_button = tk.Button(controls, text="Clear", command=self._clear_terminal,
									   relief="raised", cursor="hand2")
		self.clear_button.grid(row=0, column=2, sticky="ew", pady=2)

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

		sidebar = ttk.LabelFrame(self.root, text="Predefined Inputs", padding=12)
		sidebar.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=12)
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
		
		# Variable to track inline editing
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
		if not self.submissions_dir.exists():
			try:
				self.submissions_dir.mkdir(parents=True, exist_ok=True)
			except OSError as err:
				messagebox.showerror("Directory Error", f"Could not create directory: {err}")
				return

		try:
			python_files = sorted(self.submissions_dir.glob("*.py"))
			file_names = [file.name for file in python_files]
		except OSError as err:
			messagebox.showerror("Directory Error", f"Could not read directory: {err}")
			file_names = []

		self.file_combo["values"] = file_names

		if file_names and (not self.file_var.get() or self.file_var.get() not in file_names):
			self.file_var.set(file_names[0])
		elif not file_names:
			self.file_var.set("")

	def _browse_directory(self) -> None:
		initial_dir = self.submissions_dir if self.submissions_dir.exists() else BASE_DIR
		selected_dir = filedialog.askdirectory(
			title="Select Submissions Directory",
			initialdir=str(initial_dir)
		)
		
		if selected_dir:
			new_dir = Path(selected_dir)
			if new_dir.exists():
				self.submissions_dir = new_dir
				self._save_config()
				self._refresh_file_list()
				messagebox.showinfo("Directory Changed", f"Submissions directory set to:\n{new_dir}")
			else:
				messagebox.showerror("Directory Error", "The selected directory does not exist.")

	def _run_selected_file(self) -> None:
		if self.process and self.process.poll() is None:
			messagebox.showinfo("Process Running", "A process is already running. Stop it before starting a new one.")
			return

		selected_file = self.file_var.get()
		if not selected_file:
			messagebox.showwarning("No File Selected", "Please choose a submission file to run.")
			return

		script_path = self.submissions_dir / selected_file
		if not script_path.exists():
			messagebox.showerror("File Missing", f"Could not find {selected_file} in submissions directory.")
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
		if value:
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
		
		# If already editing, finish that edit first
		if self.edit_entry:
			self._finish_edit()
			return
		
		index = selection[0]
		self.edit_index = index
		
		# Get the position and size of the selected item
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
		
		# Update the predefined inputs list
		if new_value.strip():  # Only save if not empty
			self.predefined_inputs[self.edit_index] = new_value
			self._save_predefined_inputs()
			self._reload_predefined_listbox()
			
			# Reselect the edited item
			self.predefined_listbox.selection_set(self.edit_index)
			self.predefined_listbox.see(self.edit_index)
		
		# Clean up
		self.edit_entry.destroy()
		self.edit_entry = None
		self.edit_index = None

	def _cancel_edit(self) -> None:
		"""Cancel editing without saving changes"""
		if not self.edit_entry:
			return
		
		# Clean up
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
		new_value = self.new_input_var.get().strip()
		if not new_value:
			return

		self.predefined_inputs.append(new_value)
		self._save_predefined_inputs()
		self._reload_predefined_listbox()
		self.new_input_var.set("")

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
		# Bind Ctrl+MouseWheel for zoom
		self.root.bind("<Control-MouseWheel>", self._handle_mouse_zoom)
		# Bind Ctrl+Plus and Ctrl+Minus for zoom
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
		
		listbox_font = ("TkDefaultFont", new_font_size)
		self.predefined_listbox.configure(font=listbox_font)
		
		# Update control buttons (tk.Button) font
		button_font = ("TkDefaultFont", new_font_size)
		self.run_button.configure(font=button_font)
		self.stop_button.configure(font=button_font)
		self.clear_button.configure(font=button_font)
		
		# Update menu bar font - use a specific font tuple
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
						else:
							self.submissions_dir = SUBMISSIONS_DIR
			except (json.JSONDecodeError, ValueError, KeyError):
				self.zoom_level = 1.0
				self.submissions_dir = SUBMISSIONS_DIR

	def _save_config(self) -> None:
		config = {
			"zoom_level": self.zoom_level,
			"submissions_dir": str(self.submissions_dir)
		}
		CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def main() -> None:
	if not SUBMISSIONS_DIR.exists():
		SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)

	root = tk.Tk()
	PythonTesterApp(root)
	root.mainloop()


if __name__ == "__main__":
	main()
