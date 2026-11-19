"""Offline browser rendering of social-preview.html. No site dependencies.

Use tools/.venv/Scripts/python; start the local preview server first.
Uses the supplied AGENT_BROWSER_CDP
endpoint without discovering/launching another browser. If screenshot capture
is unavailable, an explicitly reported browser-canvas fallback uses the same
loaded fonts, source image, and HTML layout. Never claims that is a screenshot.
"""
import argparse
import base64
import json
from pathlib import Path
import struct

from browser_cdp import Browser

ROOT = Path(__file__).resolve().parents[1]


def render(base):
    browser = Browser()
    def evaluate(js):
        return browser.evaluate("document.querySelector('iframe').contentWindow.eval(" + json.dumps(js) + ")")
    try:
        browser.call("Page.navigate", {"url": base + "/tools/render-frame.html"})
        browser.evaluate("""new Promise(resolve=>{const end=Date.now()+10000;function tick(){
          if(location.pathname.endsWith('render-frame.html')&&document.querySelector('iframe')?.contentDocument?.readyState==='complete')return resolve(true);
          if(Date.now()>end)return resolve(false);setTimeout(tick,30)}tick()})""")
        fonts = evaluate("""(async()=>{
          await Promise.all([document.fonts.load('italic 96px "Instrument Serif"'),document.fonts.load('500 13px Inter')]);
          const img=document.querySelector('main img');if(!img.complete)await new Promise((r,j)=>{img.onload=r;img.onerror=j});
          return [...document.fonts].filter(f=>f.status==='loaded').map(f=>f.family);
        })()""")
        if not all(any(name in f for f in fonts) for name in ("Instrument Serif", "Inter")):
            raise RuntimeError("Required site fonts did not load; social rendering stopped.")
        method = "HTML screenshot"
        try:
            result = browser.capture_frame(1200, 630)
            method = f'HTML screenshot, {result["tiles"]} native unscaled tiles in attached browser'
            content = base64.b64decode(result["data"])
        except RuntimeError as error:
            if "pane_hidden" not in str(error):
                raise
            method = "Browser canvas fallback, not a screenshot (HTML capture unavailable: pane_hidden)"
            value = evaluate("""(()=>{
              const main=document.querySelector('main'),canvas=document.createElement('canvas');
              canvas.width=1200;canvas.height=630;
              const ctx=canvas.getContext('2d'),origin=main.getBoundingClientRect();
              ctx.fillStyle=getComputedStyle(main).backgroundColor;ctx.fillRect(0,0,1200,630);
              const img=main.querySelector('img'),c=getComputedStyle(img);
              const w=parseFloat(c.width),h=parseFloat(c.height),x=img.offsetLeft,y=img.offsetTop;
              ctx.save();ctx.translate(x+w/2,y+h/2);ctx.transform(...[new DOMMatrix(c.transform).a,new DOMMatrix(c.transform).b,new DOMMatrix(c.transform).c,new DOMMatrix(c.transform).d,0,0]);
              ctx.drawImage(img,-w/2,-h/2,w,h);ctx.restore();
              for(const e of main.querySelectorAll('.label,h1')){
                const style=getComputedStyle(e),r=e.getBoundingClientRect();
                ctx.font=`${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
                ctx.fillStyle=style.color;ctx.letterSpacing=style.letterSpacing;
                const metrics=ctx.measureText('Mg'),line=parseFloat(style.lineHeight);
                const ascent=metrics.fontBoundingBoxAscent,descent=metrics.fontBoundingBoxDescent;
                const lines=e.innerText.split('\\n');
                lines.forEach((text,i)=>ctx.fillText(text,r.left-origin.left,r.top-origin.top+(line-ascent-descent)/2+ascent+i*line));
              }
              return canvas.toDataURL('image/png').split(',')[1];
            })()""")
            content = base64.b64decode(value)
        if struct.unpack(">II", content[16:24]) != (1200, 630):
            raise RuntimeError(f"Social preview dimensions are incorrect: {struct.unpack('>II', content[16:24])}.")
        target = ROOT / "assets/images/social-preview.png"
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(target)
        # Embed just the two monogram glyphs so SVG image rendering needs no
        # external font request (external fonts are blocked in SVG image mode).
        font = evaluate("""(async()=>{
          const css=await (await fetch('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@1&text=vg&display=swap')).text();
          const url=css.match(/src:\\s*url\\(([^)]+)\\)/)[1].replace(/['"]/g,'');
          const data=new Uint8Array(await (await fetch(url)).arrayBuffer());
          let binary='';for(const byte of data)binary+=String.fromCharCode(byte);
          return {base64:btoa(binary),format:css.match(/format\\(['"]([^'"]+)/)?.[1]||'woff2'};
        })()""")
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">\n'
            '<defs><style>@font-face{font-family:"Instrument Serif";font-style:italic;font-weight:400;'
            f'src:url("data:font/{font["format"]};base64,{font["base64"]}") format("{font["format"]}")'
            '}</style></defs>\n<rect width="64" height="64" rx="12" fill="#0B0B0B"/>\n'
            '<text x="13" y="44" fill="#F2EEE6" font-family="Instrument Serif, serif" font-style="italic" font-size="43" letter-spacing="-3">vg</text>\n</svg>\n'
        )
        (ROOT / "assets/favicon.svg").write_text(svg, encoding="utf-8")
        report = {"method": method, "size": [1200, 630], "loaded_fonts": sorted(set(fonts)), "favicon": "Embedded Instrument Serif italic vg glyphs"}
        folder = ROOT / "tools/screenshots"
        folder.mkdir(exist_ok=True)
        (folder / "social-render-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
    finally:
        browser.socket.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    render(parser.parse_args().base_url.rstrip("/"))
