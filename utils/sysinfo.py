"""
System Diagnostics Utilities for Billion-Air-Flow

Provides CPU, RAM, and SSD/HDD diagnostic info plus a top-style dashboard.
Works on Windows and Linux (Ubuntu).
"""

import platform
import psutil
import shutil
import subprocess
import re

def get_cpu_info():
    system = platform.system()
    raw_name = ""

    if system == "Windows":
        # Try PowerShell first
        try:
            cmd = [
                "powershell",
                "-Command",
                "(Get-CimInstance Win32_Processor).Name"
            ]
            output = subprocess.check_output(cmd, universal_newlines=True).strip()
            if output:
                raw_name = output
        except Exception:
            pass

        # Fallback: WMIC
        if not raw_name:
            try:
                output = subprocess.check_output(
                    ["wmic", "cpu", "get", "Name"], universal_newlines=True
                ).strip().split("\n")
                if len(output) > 1:
                    raw_name = output[1].strip()
            except Exception:
                pass

    elif system == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        raw_name = line.split(":")[1].strip()
                        break
        except Exception:
            pass

    # Last resort
    if not raw_name:
        raw_name = platform.processor()

    friendly_name = make_friendly_cpu_name(raw_name)

    cpu_count = psutil.cpu_count(logical=True)
    cpu_physical = psutil.cpu_count(logical=False)

    freq = psutil.cpu_freq()
    cpu_speed = {
        "Min (MHz)": round(freq.min, 2),
        "Max (MHz)": round(freq.max, 2),
        "Current (MHz)": round(freq.current, 2)
    } if freq else "Unavailable"

    return {
        "CPU Name (Raw)": raw_name,
        "CPU Name (Friendly)": friendly_name,
        "Cores (Physical)": cpu_physical,
        "Threads (Logical)": cpu_count,
        "Clock Speed": cpu_speed
    }

def make_friendly_cpu_name(raw_name):
    if not raw_name:
        return "Unknown CPU"

    name = raw_name
    # Clean up trademarks and clutter
    name = re.sub(r"\(R\)|\(TM\)|CPU|@.*GHz", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip()

    # Try to detect Intel gen
    match = re.search(r"(i3|i5|i7|i9)-(\d{3,5})", name)
    if match:
        family, model_num = match.groups()
        model_num = int(model_num)
        if model_num < 1000:
            generation = "1st Gen (very old)"
        elif model_num < 10000:  # e.g. 2600 -> 2nd gen, 8700 -> 8th gen
            generation = f"{str(model_num)[0]}th Gen"
        else:  # e.g. 10700 -> 10th gen
            generation = f"{str(model_num)[:2]}th Gen"
        return f"Intel Core {family}-{model_num} ({generation})"

    # AMD Ryzen parsing
    if "Ryzen" in name:
        return name  # already human-friendly

    return name

def get_ram_info():
    vm = psutil.virtual_memory()

    # Round to nearest "whole GB"
    total_gb = vm.total / (1000 ** 3)

    ram_speed = None
    system = platform.system()

    if system == "Windows":
        try:
            cmd = [
                "powershell",
                "-Command",
                "Get-CimInstance Win32_PhysicalMemory | Select-Object -ExpandProperty Speed"
            ]
            output = subprocess.check_output(cmd, universal_newlines=True).strip().splitlines()
            speeds = [int(s) for s in output if s.isdigit()]
            if speeds:
                # If multiple sticks, report unique values
                ram_speed = list(sorted(set(speeds)))
        except Exception:
            ram_speed = None

    elif system == "Linux":
        try:
            # dmidecode requires root
            output = subprocess.check_output(
                ["dmidecode", "-t", "memory"],
                stderr=subprocess.DEVNULL,
                universal_newlines=True
            )
            speeds = re.findall(r"Configured Clock Speed: (\d+) MT/s", output)
            if not speeds:
                speeds = re.findall(r"Speed: (\d+) MT/s", output)
            if speeds:
                ram_speed = list(sorted(set(int(s) for s in speeds if s.isdigit())))
        except Exception:
            ram_speed = None

    return {
        "Total RAM (GB)": total_gb,
        "Memory Speed (MHz)": ram_speed
    }

def get_storage_info():
    system = platform.system()
    drives = []

    if system == "Windows":
        try:
            cmd = [
                "powershell",
                "-Command",
                "Get-PhysicalDisk | Select-Object FriendlyName, Manufacturer, SerialNumber, Size, BusType | Format-List"
            ]
            output = subprocess.check_output(cmd, universal_newlines=True)

            blocks = re.split(r"\n\s*\n", output.strip())
            for block in blocks:
                drive_info = {}
                for line in block.splitlines():
                    if ":" in line:
                        key, val = line.split(":", 1)
                        drive_info[key.strip()] = val.strip()
                if drive_info:
                    size = drive_info.get("Size")
                    drives.append({
                        "Model": drive_info.get("FriendlyName"),
                        "Manufacturer": drive_info.get("Manufacturer"),
                        "Serial": drive_info.get("SerialNumber"),
                        # ✅ Use decimal GB
                        "Size (GB)": round(int(size) / (1000**3), 2) if size and size.isdigit() else None,
                        "BusType": drive_info.get("BusType")
                    })
        except Exception as e:
            drives.append({"Error": f"Could not retrieve drive info: {e}"})

    elif system == "Linux":
        try:
            output = subprocess.check_output(
                ["lsblk", "-d", "-o", "NAME,MODEL,VENDOR,SERIAL,SIZE,TRAN"],
                stderr=subprocess.DEVNULL,
                universal_newlines=True
            ).strip().split("\n")

            headers = output[0].split()
            for line in output[1:]:
                parts = line.split(None, len(headers)-1)
                if len(parts) >= 6:
                    name, model, vendor, serial, size, tran = parts
                    # SIZE is already human-readable (e.g. "512G")
                    drives.append({
                        "Device": f"/dev/{name}",
                        "Model": model,
                        "Vendor": vendor,
                        "Serial": serial,
                        "Size": size,  # leave lsblk formatting
                        "BusType": tran
                    })
        except Exception as e:
            drives.append({"Error": f"Could not retrieve drive info: {e}"})

    return drives


def get_abbreviated_system_diagnostics():
    sysinfo = get_system_diagnostics()

    # CPU
    cpu_raw = sysinfo["CPU"].get("CPU Name (Raw)", "Unknown CPU")

    # RAM
    ram_total = sysinfo["RAM"].get("Total RAM (GB)", "?")
    ram_speed = sysinfo["RAM"].get("Memory Speed (MHz)", [])
    ram_speed_str = ""
    if ram_speed:
        ram_speed_str = f"-{','.join(str(s) for s in ram_speed)}"
    ram_str = f"{ram_total}GB DDR{ram_speed_str}" if ram_speed_str else f"{ram_total}GB"

    # Storage
    storage_parts = []
    for d in sysinfo["Storage"]:
        model = d.get("Model", "UnknownDrive")
        size = d.get("Size (GB)") or d.get("Total Size (GB)") or d.get("Size")
        size_str = f"{int(round(size))}GB" if isinstance(size, (int, float)) else str(size)
        storage_parts.append(f"{model} {size_str}")

    storage_str = " | ".join(storage_parts)

    return f"{cpu_raw} | {ram_str} RAM | {storage_str}"


def get_system_diagnostics():
    return {
        "CPU": get_cpu_info(),
        "RAM": get_ram_info(),
        "Storage": get_storage_info()
    }

def make_bar(fraction, width=20):
    """Make a simple [#####.....] bar."""
    filled = int(round(width * fraction))
    empty = width - filled
    return "[" + "#" * filled + "." * empty + "]"

def snapshot_dashboard():
    """Print a one-time system usage dashboard (CPU + RAM)."""
    # Adjust bar width to terminal size
    cols = shutil.get_terminal_size((80, 20)).columns
    bar_width = max(10, min(40, cols // 4))

    lines = []

    # CPU usage
    cpu_percents = psutil.cpu_percent(percpu=True)
    lines.append("CPU Usage:")
    for i, pct in enumerate(cpu_percents):
        bar = make_bar(pct/100, width=bar_width)
        lines.append(f" Core {i:2}: {bar} {pct:5.1f}%")

    # RAM usage
    vm = psutil.virtual_memory()
    ram_fraction = vm.used / vm.total
    used_gb = vm.used / (1024**3)
    total_gb = vm.total / (1024**3)
    bar = make_bar(ram_fraction, width=bar_width)
    lines.append("RAM Usage:")
    lines.append(f" {bar} {ram_fraction*100:5.1f}% "
                 f"({round(used_gb,1)}GB / {round(total_gb):d}GB)")    

    output = str("\n".join(lines))

    return output  # also return string if you want to log/use elsewhere

