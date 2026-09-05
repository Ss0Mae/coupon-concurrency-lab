"""collect.py 수정 후 기존 실행을 원시 파일에서 다시 집계해 runs.jsonl 을 재작성한다. usage: recollect.py <exp>"""
import json, subprocess, sys
exp = sys.argv[1]
path = f"results/{exp}/runs.jsonl"
recs = [json.loads(l) for l in open(path) if l.strip()]
out = []
for r in recs:
    args = ["--exp", r["exp"], "--tag", r.get("tag", ""), "--id", r["id"], "--strategy", r["strategy"], "--vus", str(r["vus"]), "--rep", r["rep"],
            "--start", repr(r["start"]), "--end", repr(r["end"]), "--qty", str(r["qty"]), "--mode", r["mode"], "--pool", str(r["pool"]), "--raw", f"results/{exp}/raw"]
    res = subprocess.run([".venv/bin/python", "bench/collect.py"] + args, capture_output=True, text=True)
    if res.returncode != 0:
        print("FAILED", r["id"], res.stderr[-300:]); out.append(json.dumps(r, ensure_ascii=False)); continue
    out.append(res.stdout.strip())
open(path, "w").write("\n".join(out) + "\n")
print(exp, "recollected", len(out))
