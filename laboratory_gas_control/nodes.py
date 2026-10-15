import tkinter as tk
from tkinter import messagebox, scrolledtext
import time
import csv


class Node:
    def __init__(self, node_id, name, flow_device, temperature, valve_output, fmeasure,fsetpoint,valve_open,tk_ref):
        self.node_id = node_id
        self.name = name
        self.flow_device=flow_device
        self.temperature = temperature
        self.valve_output = valve_output
        self.fmeasure = fmeasure
        self.fsetpoint=fsetpoint
        self.valve_open=valve_open
        self.tk_ref=tk_ref
        self.gui_setpoint_var = None
        self.stop_count=True


    def update_temperature(self,label):
            try:
                # params = [{'node': self.node_id,'proc_nr': 33, 'parm_nr': 7, 'parm_type': propar.PP_TYPE_INT16}]
                value = self.flow_device.readParameter(142)
                self.temperature = round(value, 3)  # Round to 3 decimal places
                label.config(text=f"Temp: {self.temperature} °C")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to update temperature: {e}")

    def update_valve_output(self,label):
        try:
            value = self.flow_device.readParameter(55)
            self.valve_output=value
            label.config(text=f"V.output in 24-bit: {self.valve_output}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update valve output: {e}")

    def measure(self,label):
        try:
            # params = [{'node': self.node_id, 'proc_nr': 33, 'parm_nr': 6, 'parm_type': propar.PP_TYPE_INT16}]
            value = self.flow_device.readParameter(8)
            self.fmeasure=value
            label.config(text=f"Measure: {value}")
            # {value:.4f}
            # move_entry.delete(0, tk.END)  # Clear previous value
            # move_entry.insert(0, f"{self.valve_output:.3f}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update valve output: {e}")
            
    def setpoint(self, value):
        try:
            float_value = float(value)
            
            # 2. Convert to int for the device and GUI
            int_value = int(float_value)
            
            # 3. Store the PRECISE float value for the _increment_loop
            self.fsetpoint = float_value  # <-- THE CRITICAL FIX
            
            # 4. Send the INTEGER value to the device
            self.flow_device.setpoint = int_value
            
            print(f"Setpoint set-{self.name}: {int_value} (from precise {float_value})")

            # 5. (GUI SYNC) Update the GUI's StringVar with the INTEGER value
            if hasattr(self, 'gui_setpoint_var') and self.gui_setpoint_var:
                self.gui_setpoint_var.set(str(int_value))

            # Read the inserted parameter back to be sure
            read_back = self.flow_device.readParameter(9) 
            print(f"Setpoint readback-{self.name}: {read_back}")
            # self.measure()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to set flow: {e}")
    # .......................................................................................................................  
    def update_open_valve(self,label):
        try:
            # params = [{'node': self.node_id, 'proc_nr': 33, 'parm_nr': 6, 'parm_type': propar.PP_TYPE_INT16}]
            value = self.flow_device.readParameter(234)
            self.valve_open=round(value, 3)
            label.config(text=f"valve open: {self.valve_open:.3f} %")
            # move_entry.delete(0, tk.END)  # Clear previous value
            # move_entry.insert(0, f"{self.valve_output:.3f}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update valve open: {e}")
        
    def open_valve(self,value):
        try:
            
            # Try converting the value to float
            value = float(value)
            # If successful, write the value to the device
            status = self.flow_device.writeParameter(42, value)
            self.status = status
            messagebox.showinfo("Success", f"Valve opened: {value:.3f}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open valve: {e}")
            
# .............................................................................................................................
    def run_increment_count(self, set_value, speed):
        print(speed)
        self.stop_count = False
        self.target_value = int(set_value)
        self.increment = float(speed) * 2  # every 2 seconds we add this
        self._increment_loop()

    def _increment_loop(self):
        if self.stop_count:
            return

        try:
            # Convert self.fsetpoint (which is a string) to a float
            current = float(self.fsetpoint)

            target = self.target_value
            inc = self.increment

            if target < current:
                new_value = current - inc
                if new_value < target:
                    new_value = target
            elif target > current:
                new_value = current + inc
                if new_value > target:
                    new_value = target
            else:
                # This check should now work correctly since both are numbers
                if current == target:
                    messagebox.showinfo("Info", "Set value has already been satisfied!")
                return

            # self.setpoint() will now receive a float
            self.setpoint(new_value)

            if new_value != target:
                # Schedule next increment after 2000 ms (2 seconds)
                self.tk_ref.after(2000, self._increment_loop)
        
        except ValueError:
            messagebox.showerror("Error", f"Invalid current setpoint value: {self.fsetpoint}. Cannot perform increment.")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred in _increment_loop: {e}")

    """ def run_increment_coun(self,set_value, speed):
        self.stop_count=False
        set_value=int(set_value)
        increment=float(speed)*2 # we will trigger the setpoint every 2 seconds
        if set_value < self.fsetpoint: # we will be decreasing
            while self.stop_count==False and set_value < self.fsetpoint:
                self.setpoint(self.fsetpoint-increment)
                time.sleep(2)
        elif set_value > self.fsetpoint: # we will be increasing
            while self.stop_count==False and set_value > self.fsetpoint:
                self.setpoint(self.fsetpoint+increment)
                time.sleep(2)
        else:
            messagebox.showinfo("Set value has been already satisfied!") """
            
    def stop_increment_count(self):
        self.stop_count=True
# ..............................................................................................................................
    # def initialize_csv(self,spec_node):
    #     # Open the file once and keep the file object in memory
    #     fieldname=["setpoint","measure","valve_output"]
    #     self.CSV = open(f"csvData_{spec_node}.csv", 'a', newline='')  # Open in append mode
    #     self.writer = csv.DictWriter(self.CSV, fieldnames=fieldname)
    
    #     # If the file is empty, write the header (optional check)
    #     if self.CSV.tell() == 0:  # Only write header if the file is empty
    #         self.writer.writeheader()

    # # Function to append data to the CSV file
    # def append_to_csv(self):
    #     # self.writer = csv.DictWriter(self.CSV, fieldnames=fieldnames)
    #     self.writer.writerow({'setpoint': self.fsetpoint, 'measure': self.fmeasure, "valve_output": self.valve_output})
    #     self.CSV.flush()
        
# Standard mass flow in ln/min (20�C, 1.01325 bar (a)) air or g/h H2O equivalent","fbnr":22,"group0":3,"group1":"","group2":"","highly secured":False,"longname":"Standard flow",
# "max":3.40282E38,"min":-3.40282E38,"name":"NormMasFlw","parameter":253,"poll":False,"process":113,"read":True,"secured":True,"varlength":"","vartype":"f","vartype2":"","write":True},


# Nodes  Node 1: {'address': 4, 'type': 'DMFC', 'serial': 'M24207457D', 'id': '\x07SNM24207457D', 'channels': 1}


# Valve hold current/voltage at %0 setp (example: 0.8, Hold = ValveOpen * 0.8)","fbnr":28,"group0":8,"group1":"",
# "group2":"","highly secured":False,"longname":"Valve zero hold","max":1,"min":0,"name":"VlvZeroHld","parameter":234,
# "poll":False,"process":114,"read":True,"secured":True,"varlength":"","vartype":"f","vartype2":"","write":True},