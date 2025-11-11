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
		self._build_layout()
		self._load_predefined_inputs()
		self._refresh_file_list()
		self._poll_output_queue()
		self._setup_zoom_bindings()
		self._apply_zoom()  # Apply loaded zoom level

		self.root.protocol("WM_DELETE_WINDOW", self._on_close)

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

		self.run_button = ttk.Button(controls, text="Run", command=self._run_selected_file)
		self.run_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

		self.stop_button = ttk.Button(controls, text="Stop", command=self._stop_process, state="disabled")
		self.stop_button.grid(row=0, column=1, sticky="ew", padx=(0, 6))

		self.clear_button = ttk.Button(controls, text="Clear", command=self._clear_terminal)
		self.clear_button.grid(row=0, column=2, sticky="ew")

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

		ttk.Label(label_row, text="Double-click to send (# for labels)").grid(row=0, column=0, sticky="w")

		move_up_button = ttk.Button(label_row, text="↑", width=3, command=self._move_predefined_up)
		move_up_button.grid(row=0, column=1, padx=(6, 3))

		move_down_button = ttk.Button(label_row, text="↓", width=3, command=self._move_predefined_down)
		move_down_button.grid(row=0, column=2)

		self.predefined_listbox = tk.Listbox(sidebar, height=15)
		self.predefined_listbox.grid(row=1, column=0, sticky="nsew", pady=(6, 6))
		self.predefined_listbox.bind("<Double-Button-1>", self._handle_predefined_double_click)

		predefined_buttons = ttk.Frame(sidebar)
		predefined_buttons.grid(row=2, column=0, sticky="ew", pady=(0, 12))
		predefined_buttons.columnconfigure(0, weight=1)
		predefined_buttons.columnconfigure(1, weight=1)

		remove_button = ttk.Button(predefined_buttons, text="Remove", command=self._remove_selected_predefined)
		remove_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

		send_button = ttk.Button(predefined_buttons, text="Send", command=self._send_selected_predefined)
		send_button.grid(row=0, column=1, sticky="ew")

		ttk.Label(sidebar, text="Add New Input").grid(row=3, column=0, sticky="w")

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

		# Launch background reader to keep UI responsive.
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
			
			# Skip labels (entries starting with #)
			if not value.strip().startswith("#"):
				self._send_to_process(value)
			
			# Select the next item in the list
			next_index = current_index + 1
			if next_index < self.predefined_listbox.size():
				self.predefined_listbox.selection_clear(0, tk.END)
				self.predefined_listbox.selection_set(next_index)
				self.predefined_listbox.see(next_index)

	def _handle_predefined_double_click(self, event: tk.Event) -> None:
		self._send_selected_predefined()

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
		
		# Select the next item, or the last item if we removed the last one
		if len(self.predefined_inputs) > 0:
			if index < len(self.predefined_inputs):
				# Select the item that moved into the deleted item's position
				self.predefined_listbox.selection_set(index)
				self.predefined_listbox.see(index)
			else:
				# We removed the last item, select the new last item
				self.predefined_listbox.selection_set(len(self.predefined_inputs) - 1)
				self.predefined_listbox.see(len(self.predefined_inputs) - 1)

	def _move_predefined_up(self) -> None:
		selection = self.predefined_listbox.curselection()
		if not selection:
			return

		index = selection[0]
		if index == 0:
			return  # Already at the top

		# Swap with the item above
		self.predefined_inputs[index], self.predefined_inputs[index - 1] = \
			self.predefined_inputs[index - 1], self.predefined_inputs[index]
		
		self._save_predefined_inputs()
		self._reload_predefined_listbox()
		
		# Keep the item selected at its new position
		self.predefined_listbox.selection_set(index - 1)
		self.predefined_listbox.see(index - 1)

	def _move_predefined_down(self) -> None:
		selection = self.predefined_listbox.curselection()
		if not selection:
			return

		index = selection[0]
		if index >= len(self.predefined_inputs) - 1:
			return  # Already at the bottom

		# Swap with the item below
		self.predefined_inputs[index], self.predefined_inputs[index + 1] = \
			self.predefined_inputs[index + 1], self.predefined_inputs[index]
		
		self._save_predefined_inputs()
		self._reload_predefined_listbox()
		
		# Keep the item selected at its new position
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

	def _save_predefined_inputs(self) -> None:
		PREDEFINED_INPUTS_PATH.write_text(json.dumps(self.predefined_inputs, indent=2), encoding="utf-8")

	def _reload_predefined_listbox(self) -> None:
		self.predefined_listbox.delete(0, tk.END)
		for i, item in enumerate(self.predefined_inputs):
			self.predefined_listbox.insert(tk.END, item)
			# Color labels (entries starting with #) differently
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

	def _apply_zoom(self) -> None:
		# Calculate font size based on zoom level
		base_font_size = 9
		new_font_size = int(base_font_size * self.zoom_level)
		
		# Update default font for all ttk widgets
		style = ttk.Style()
		style.configure(".", font=("TkDefaultFont", new_font_size))
		
		# Update text widgets font
		text_font_size = int(10 * self.zoom_level)
		self.output_text.configure(font=("TkFixedFont", text_font_size))
		
		# Update entry widgets and combobox font
		entry_font = ("TkDefaultFont", new_font_size)
		self.file_combo.configure(font=entry_font)
		self.manual_entry.configure(font=entry_font)
		self.new_input_entry.configure(font=entry_font)
		
		# Update listbox font
		listbox_font = ("TkDefaultFont", new_font_size)
		self.predefined_listbox.configure(font=listbox_font)

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
							# Directory doesn't exist, revert to default
							self.submissions_dir = SUBMISSIONS_DIR
			except (json.JSONDecodeError, ValueError, KeyError):
				# If config is corrupted, use defaults
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
