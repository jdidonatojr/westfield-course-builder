from http.server import BaseHTTPRequestHandler
import os
import json
import urllib.parse
import urllib.request
import urllib.error


# ---------------------------------------------------------------------------
# STEP 2a TEST ENDPOINT
# Purpose: given a CloudConvert job_id, wait for the job to finish and return
#          the download link for the converted PDF.
# How to test in a browser:
#   https://aila-course-files.vercel.app/api/test_cloudconvert_fetch?job_id=YOUR_JOB_ID
# ---------------------------------------------------------------------------

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # 1. Get the CloudConvert key that's already saved on this project.
            api_key = os.environ.get("CLOUDCONVERT_API_KEY", "").strip()
            if not api_key:
                return self._send(500, {
                    "ok": False,
                    "error": "No CloudConvert API key found in the environment."
                })

            # 2. Read the job_id from the web address (?job_id=...).
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            job_id = params.get("job_id", [""])[0].strip()
            if not job_id:
                return self._send(400, {
                    "ok": False,
                    "error": "Please add ?job_id=... to the web address."
                })

            # 3. Ask CloudConvert's "wait here until finished" endpoint.
            #    (Different base address: sync.api.cloudconvert.com)
            url = "https://sync.api.cloudconvert.com/v2/jobs/" + urllib.parse.quote(job_id)
            req = urllib.request.Request(url)
            req.add_header("Authorization", "Bearer " + api_key)

            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            data = body.get("data", {})
            job_status = data.get("status", "unknown")
            tasks = data.get("tasks", [])

            # 4. If the whole job failed, say so plainly.
            if job_status == "error":
                return self._send(502, {
                    "ok": False,
                    "error": "CloudConvert reported the job failed.",
                    "job_status": job_status
                })

            # 5. Find the finished PDF export.
            #    First try the task named "export-pdf" (the name in our job).
            #    If that's not there, fall back to any finished export whose
            #    file ends in .pdf.
            pdf_url = None
            pdf_name = None

            for t in tasks:
                if t.get("name") == "export-pdf" and t.get("status") == "finished":
                    files = (t.get("result") or {}).get("files") or []
                    if files:
                        pdf_url = files[0].get("url")
                        pdf_name = files[0].get("filename")
                    break

            if not pdf_url:
                for t in tasks:
                    if t.get("operation") == "export/url" and t.get("status") == "finished":
                        files = (t.get("result") or {}).get("files") or []
                        for f in files:
                            name = (f.get("filename") or "").lower()
                            if name.endswith(".pdf"):
                                pdf_url = f.get("url")
                                pdf_name = f.get("filename")
                                break
                    if pdf_url:
                        break

            # 6. Report the result.
            if not pdf_url:
                return self._send(404, {
                    "ok": False,
                    "error": "Job finished but no PDF download link was found.",
                    "job_status": job_status
                })

            return self._send(200, {
                "ok": True,
                "job_status": job_status,
                "pdf_filename": pdf_name,
                "pdf_url": pdf_url
            })

        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")
            except Exception:
                pass
            return self._send(502, {
                "ok": False,
                "error": "CloudConvert returned an error.",
                "status_code": e.code,
                "detail": detail[:500]
            })
        except Exception as e:
            return self._send(500, {
                "ok": False,
                "error": "Something went wrong.",
                "detail": str(e)
            })

    # Small helper that sends a JSON reply.
    def _send(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
