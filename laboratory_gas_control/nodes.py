import tkinter as tk
from tkinter import messagebox, scrolledtext
import time
import csv


class Node:
    def __init__(self, node_id, name, flow_device, temperature, valve_output, fmeasure,fsetpoint,valve_open, CSV,writer):
        self.node_id = node_id
        self.name = name
        self.flow_device=flow_device
        self.temperature = temperature
        self.valve_output = valve_output
        self.fmeasure = fmeasure
        self.fsetpoint=fsetpoint
        self.valve_open=valve_open
        self.CSV=CSV
        self.writer=writer

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
            
    def setpoint(self,value):
        try:
            value = int(value)
            self.flow_device.setpoint = value
            self.fsetpoint=value
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