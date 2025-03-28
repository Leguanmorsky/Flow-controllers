import tkinter as tk
from tkinter import messagebox
import serial
import serial.tools.list_ports

def list_available_ports():
    ports = serial.tools.list_ports.comports()
    return [port.device for port in ports]

# Print all available COM ports
print("Available Ports:", list_available_ports())

class ELFlowControllerApp:
    def __init__(self, master):
        self.master = master
        self.master.title("EL-FLOW Prestige Controller")
        self.master.geometry("400x300")

        self.serial_port = None
        self.com_port = "COM9"
        self.baud_rate = 9600

        self.create_widgets()

    def create_widgets(self):
        tk.Label(self.master, text="Connected to:").grid(row=0, column=0, sticky="w", padx=10, pady=5)
        self.com_label = tk.Label(self.master, text=self.com_port, fg="green")
        self.com_label.grid(row=0, column=1, sticky="w", padx=10, pady=5)

        self.test_button = tk.Button(self.master, text="Test Connection", command=self.test_connection)
        self.test_button.grid(row=1, column=0, padx=10, pady=10)

        tk.Label(self.master, text="Set Flow Rate (mL/min):").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        self.flow_entry = tk.Entry(self.master)
        self.flow_entry.grid(row=2, column=1, padx=10, pady=5)

        self.set_flow_button = tk.Button(self.master, text="Set Flow", command=self.set_flow_rate)
        self.set_flow_button.grid(row=3, column=0, padx=10, pady=10)

        self.get_flow_button = tk.Button(self.master, text="Get Current Flow", command=self.get_flow_rate)
        self.get_flow_button.grid(row=3, column=1, padx=10, pady=10)

        self.response_text = tk.Text(self.master, height=10, width=40, state="disabled")
        self.response_text.grid(row=5, column=0, columnspan=2, padx=10, pady=5)

    def connect_to_device(self):
        try:
            self.serial_port = serial.Serial(self.com_port, self.baud_rate, timeout=1)
            self.log_message(f"Connected to {self.com_port}")
        except serial.SerialException as e:
            messagebox.showerror("Error", f"Failed to connect to {self.com_port}: {e}")

    def send_command(self, command):
        if self.serial_port:
            try:
                self.serial_port.write((command + "\n").encode())
                response = self.serial_port.readline().decode().strip()
                return response
            except Exception as e:
                return f"Error: {e}"
        else:
            return "No connection to the device."

    def set_flow_rate(self):
        rate = self.flow_entry.get()
        response = self.send_command(f"SET_FLOW:{rate}")
        self.log_message(f"Set Flow Rate Response: {response}")

    def get_flow_rate(self):
        response = self.send_command("GET_FLOW")
        self.log_message(f"Current Flow Rate: {response}")

    def test_connection(self):
        response = self.send_command("PING")  # Replace with a known "test" command
        self.log_message(f"Connection Test Response: {response}")
        if "OK" in response:
            messagebox.showinfo("Success", "Device is connected and responding.")
        else:
            messagebox.showerror("Error", "Device not responding.")

    def log_message(self, message):
        print(message)
        self.response_text.config(state="normal")
        self.response_text.insert("end", message + "\n")
        self.response_text.config(state="disabled")
        self.response_text.see("end")

    def close_connection(self):
        if self.serial_port:
            self.serial_port.close()
            self.log_message("Serial connection closed.")

if __name__ == "__main__":
    root = tk.Tk()
    app = ELFlowControllerApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.close_connection(), root.destroy()))
    root.mainloop()