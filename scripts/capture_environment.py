#!/usr/bin/env python3
import subprocess,json,platform,os,time
from pathlib import Path
out={"captured_at":time.strftime("%Y-%m-%dT%H:%M:%S%z"),"kernel":platform.release(),"cpu_count":os.cpu_count()}
for name,cmd in [("cpu",["lscpu"]),("memory",["free","-b"]),("compiler",["gcc","--version"]),("mounts",["findmnt","-J"]),("disk_space",["df","-B1","/"])]:
 r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 out[name]=r.stdout
out["uptime"]=Path("/proc/uptime").read_text().strip()
out["loadavg"]=Path("/proc/loadavg").read_text().strip()
print(json.dumps(out,indent=2))
