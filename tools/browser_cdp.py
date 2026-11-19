"""Offline stdlib CDP driver; native tiled screenshots optionally use Pillow."""
import base64
import json
import os
import socket
import struct
from urllib.parse import urlsplit


class Browser:
    def __init__(self):
        url = urlsplit(os.environ["AGENT_BROWSER_CDP"])
        self.socket = socket.create_connection((url.hostname, url.port), timeout=25)
        self.socket.settimeout(30)
        self.buffer = b""
        self.counter = 0
        self.events = []
        key = base64.b64encode(os.urandom(16)).decode()
        path = url.path + ("?" + url.query if url.query else "")
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {url.netloc}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.socket.sendall(request.encode())
        while b"\r\n\r\n" not in self.buffer:
            self.buffer += self.socket.recv(8192)
        headers, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        if b" 101 " not in headers.split(b"\r\n")[0]:
            raise RuntimeError(headers.decode())
        self.session = None

    def read(self, size):
        while len(self.buffer) < size:
            chunk = self.socket.recv(65536)
            if not chunk:
                raise ConnectionError("CDP socket closed")
            self.buffer += chunk
        value, self.buffer = self.buffer[:size], self.buffer[size:]
        return value

    def send(self, data, opcode=1):
        mask = os.urandom(4)
        size = len(data)
        header = bytes([0x80 | opcode])
        if size < 126:
            header += bytes([0x80 | size])
        elif size < 65536:
            header += bytes([0x80 | 126]) + struct.pack("!H", size)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", size)
        self.socket.sendall(header + mask + bytes(x ^ mask[i % 4] for i, x in enumerate(data)))

    def receive(self):
        message = b""
        while True:
            a, b = self.read(2)
            size = b & 127
            if size == 126:
                size = struct.unpack("!H", self.read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.read(8))[0]
            mask = self.read(4) if b & 128 else None
            payload = self.read(size)
            if mask:
                payload = bytes(x ^ mask[i % 4] for i, x in enumerate(payload))
            opcode = a & 15
            if opcode == 8:
                raise ConnectionError(payload.decode(errors="replace"))
            if opcode == 9:
                self.send(payload, 10)
                continue
            if opcode == 10:
                continue
            message += payload
            if a & 128:
                return json.loads(message)

    def call(self, method, params=None, browser=False):
        self.counter += 1
        request = {"id": self.counter, "method": method, "params": params or {}}
        if self.session and not browser:
            request["sessionId"] = self.session
        self.send(json.dumps(request).encode())
        while True:
            response = self.receive()
            if response.get("id") == self.counter:
                if "error" in response:
                    raise RuntimeError(f'{method}: {response["error"]}')
                return response.get("result", {})
            self.events.append(response)

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in result:
            raise RuntimeError(str(result["exceptionDetails"]))
        return result.get("result", {}).get("value")

    def capture_frame(self, width, height, selector="iframe"):
        """Capture a full-size iframe in native, unscaled viewport tiles."""
        import io
        from PIL import Image

        native = self.evaluate("({w:innerWidth,h:innerHeight,dpr:devicePixelRatio})")
        tw, th = max(4, int(native["w"]) // 4 * 4), max(4, int(native["h"]) // 4 * 4)
        selected = json.dumps(selector)
        old = self.evaluate(f"""(()=>{{const f=document.querySelector({selected});
          const old={{transform:f.style.transform,overflow:document.documentElement.style.overflow}};
          document.documentElement.style.overflow='hidden';scrollTo(0,0);return old}})()""")
        canvas = Image.new("RGB", (width, height))
        count = 0
        try:
            for y in range(0, height, th):
                for x in range(0, width, tw):
                    w, h = min(tw, width - x), min(th, height - y)
                    self.evaluate(f"""new Promise(resolve=>{{const f=document.querySelector({selected});
                      f.style.transform='translate(-{x}px,-{y}px)';f.getBoundingClientRect();
                      requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true)));
                      setTimeout(()=>resolve(false),250);
                    }})""")
                    result = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False,
                        "clip": {"x": 0, "y": 0, "width": w, "height": h, "scale": 1 / native["dpr"]}})
                    tile = Image.open(io.BytesIO(base64.b64decode(result["data"]))).convert("RGB")
                    if abs(tile.width - w) > 1 or abs(tile.height - h) > 1:
                        raise RuntimeError(f"Unexpected native tile dimensions {tile.size}, expected {(w, h)}")
                    if tile.size != (w, h):
                        tile = tile.resize((w, h), Image.Resampling.LANCZOS)
                    canvas.paste(tile, (x, y))
                    count += 1
            buffer = io.BytesIO()
            canvas.save(buffer, "PNG")
            return {"data": base64.b64encode(buffer.getvalue()).decode(), "tiles": count, "native_tile": [tw, th]}
        finally:
            self.evaluate(f"""(()=>{{document.querySelector({selected}).style.transform={json.dumps(old["transform"])};
              document.documentElement.style.overflow={json.dumps(old["overflow"])}}})()""")
