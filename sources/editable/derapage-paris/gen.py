# Generates the Paris roadside props of Pistouille as SVG (2x), then WebP via ImageMagick/librsvg.
import subprocess, sys, os
OUT_SVG = sys.argv[1]; OUT_WEBP = sys.argv[2]
os.makedirs(OUT_SVG, exist_ok=True); os.makedirs(OUT_WEBP, exist_ok=True)
INK = '#2c2638'
def svg(w, h, body, defs=''):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><defs>{defs}</defs>{body}</svg>'

COMMON_DEFS = f'''
<linearGradient id="glass" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#cfeeff"/><stop offset=".45" stop-color="#7fb9ea"/><stop offset="1" stop-color="#3d64a6"/></linearGradient>
<linearGradient id="zinc" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a9bad0"/><stop offset="1" stop-color="#5d6f8a"/></linearGradient>
<linearGradient id="iron" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#1d2f2a"/><stop offset=".45" stop-color="#3f6b5c"/><stop offset="1" stop-color="#16241f"/></linearGradient>
<radialGradient id="glow"><stop offset="0" stop-color="#fff6c4" stop-opacity=".95"/><stop offset=".55" stop-color="#ffd76a" stop-opacity=".35"/><stop offset="1" stop-color="#ffd76a" stop-opacity="0"/></radialGradient>
<linearGradient id="warm" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff1b8"/><stop offset="1" stop-color="#f6b44a"/></linearGradient>
'''

def window(x, y, w, h, arched=False):
    top = f'M{x},{y+w/2} A{w/2},{w/2} 0 0 1 {x+w},{y+w/2}' if arched else f'M{x},{y}L{x+w},{y}'
    frame = f'<rect x="{x-6}" y="{y-8}" width="{w+12}" height="{h+14}" rx="4" fill="#fbf3df" stroke="{INK}" stroke-width="3"/>'
    if arched:
        glass = f'<path d="M{x},{y+h} L{x},{y+w/2} A{w/2},{w/2} 0 0 1 {x+w},{y+w/2} L{x+w},{y+h} Z" fill="url(#glass)" stroke="{INK}" stroke-width="3"/>'
    else:
        glass = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="url(#glass)" stroke="{INK}" stroke-width="3"/>'
    cross = f'<line x1="{x+w/2}" y1="{y+2}" x2="{x+w/2}" y2="{y+h}" stroke="#f4f7ff" stroke-width="4"/><line x1="{x}" y1="{y+h*.42}" x2="{x+w}" y2="{y+h*.42}" stroke="#f4f7ff" stroke-width="4"/>'
    shine = f'<path d="M{x+5},{y+h*.36} L{x+w*.36},{y+6} L{x+w*.36+9},{y+6} L{x+5},{y+h*.36+12}Z" fill="#ffffff" opacity=".55"/>'
    sill = f'<rect x="{x-9}" y="{y+h+4}" width="{w+18}" height="8" rx="2" fill="#e6d3ab" stroke="{INK}" stroke-width="3"/>'
    return frame + glass + shine + cross + sill

def railing(x0, x1, y, h=22):
    s = f'<rect x="{x0}" y="{y}" width="{x1-x0}" height="5" fill="#2b2d3a"/><rect x="{x0}" y="{y+h}" width="{x1-x0}" height="5" fill="#2b2d3a"/>'
    xx = x0 + 6
    while xx < x1 - 4:
        s += f'<line x1="{xx}" y1="{y+4}" x2="{xx}" y2="{y+h}" stroke="#2b2d3a" stroke-width="3"/>'
        xx += 9
    xx = x0 + 15
    while xx < x1 - 10:
        s += f'<circle cx="{xx}" cy="{y+h/2+2}" r="5" fill="none" stroke="#2b2d3a" stroke-width="2.5"/>'
        xx += 27
    return s

def immeuble(variant):
    W, H = 384, 512
    stone = ('#f8eed6', '#e3cfa6') if variant == 0 else ('#f3e6dc', '#d9c2b4')
    awning = ('#d8322f', '#fbf3e6') if variant == 0 else ('#2f63b8', '#fbf3e6')
    shop = '#2f5d4a' if variant == 0 else '#6b2f45'
    sign = 'CAFÉ' if variant == 0 else 'BISTROT'
    defs = COMMON_DEFS + f'<linearGradient id="stone" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{stone[1]}"/><stop offset=".35" stop-color="{stone[0]}"/><stop offset="1" stop-color="{stone[1]}"/></linearGradient>'
    b = f'<ellipse cx="192" cy="500" rx="180" ry="10" fill="#000" opacity=".22"/>'
    # chimneys
    for cx in (92, 292):
        b += f'<rect x="{cx-26}" y="34" width="52" height="56" fill="#d9a07a" stroke="{INK}" stroke-width="5"/><rect x="{cx-30}" y="28" width="60" height="10" fill="#c27f5a" stroke="{INK}" stroke-width="4"/>'
        for px in (-15, 0, 15):
            b += f'<rect x="{cx+px-5}" y="12" width="10" height="18" rx="2" fill="#e8743a" stroke="{INK}" stroke-width="3"/>'
    # mansard roof
    b += f'<path d="M34,156 L58,74 L326,74 L350,156 Z" fill="url(#zinc)" stroke="{INK}" stroke-width="6" stroke-linejoin="round"/>'
    b += f'<path d="M58,74 L326,74" stroke="#d6e1ee" stroke-width="5"/>'
    for x in range(72, 320, 22):
        b += f'<line x1="{x}" y1="80" x2="{x - (x-192)*0.12}" y2="150" stroke="#4d5d76" stroke-width="2" opacity=".6"/>'
    for cx in (100, 192, 284):
        b += f'<path d="M{cx-26},150 L{cx-26},104 A26,26 0 0 1 {cx+26},104 L{cx+26},150 Z" fill="#fbf3df" stroke="{INK}" stroke-width="4"/>'
        b += f'<path d="M{cx-16},146 L{cx-16},108 A16,16 0 0 1 {cx+16},108 L{cx+16},146 Z" fill="url(#glass)" stroke="{INK}" stroke-width="3"/>'
        b += f'<line x1="{cx}" y1="94" x2="{cx}" y2="146" stroke="#f4f7ff" stroke-width="3"/>'
    # cornice
    b += f'<rect x="22" y="152" width="340" height="18" rx="3" fill="#efe0bd" stroke="{INK}" stroke-width="5"/>'
    for x in range(30, 356, 14):
        b += f'<rect x="{x}" y="170" width="7" height="6" fill="#cdb78b"/>'
    # facade
    b += f'<rect x="32" y="170" width="320" height="248" fill="url(#stone)" stroke="{INK}" stroke-width="6"/>'
    for y in range(196, 418, 26):
        b += f'<line x1="36" y1="{y}" x2="348" y2="{y}" stroke="#c9b38a" stroke-width="1.5" opacity=".6"/>'
    cols = (66, 162, 258)
    # 4th floor (small balconies), 3rd floor, 2nd floor (continuous balcony), arched noble windows
    for cx in cols: b += window(cx, 186, 60, 50)
    b += railing(40, 344, 228)
    for cx in cols: b += window(cx, 266, 60, 54)
    for cx in cols: b += f'<rect x="{cx-8}" y="318" width="76" height="6" fill="#2b2d3a"/>' + railing(cx-8, cx+68, 300, 18)
    for cx in cols: b += window(cx, 344, 60, 58, arched=True)
    b += railing(40, 344, 384)
    # string course
    b += f'<rect x="26" y="410" width="332" height="12" rx="3" fill="#efe0bd" stroke="{INK}" stroke-width="4"/>'
    # shop front
    b += f'<rect x="32" y="422" width="320" height="72" fill="{shop}" stroke="{INK}" stroke-width="6"/>'
    for x in (46, 238):
        b += f'<rect x="{x}" y="452" width="100" height="40" rx="3" fill="url(#warm)" stroke="{INK}" stroke-width="4"/>'
        b += f'<line x1="{x+50}" y1="452" x2="{x+50}" y2="492" stroke="{INK}" stroke-width="3"/>'
    b += f'<rect x="164" y="446" width="56" height="48" rx="4" fill="#3d2a24" stroke="{INK}" stroke-width="4"/><circle cx="208" cy="472" r="3.5" fill="#ffd56a"/>'
    # awning (stripes + scallops)
    b += f'<path d="M30,424 L354,424 L366,452 L18,452 Z" fill="{awning[1]}" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
    n = 12
    for i in range(0, n, 2):
        x0 = 30 + i * 324 / n; x1 = 30 + (i + 1) * 324 / n
        b0 = 18 + i * 348 / n; b1 = 18 + (i + 1) * 348 / n
        b += f'<path d="M{x0},424 L{x1},424 L{b1},452 L{b0},452 Z" fill="{awning[0]}"/>'
    for i in range(n):
        cx = 18 + (i + .5) * 348 / n
        b += f'<path d="M{cx-14.5},452 A14.5,10 0 0 0 {cx+14.5},452 Z" fill="{awning[0] if i % 2 == 0 else awning[1]}" stroke="{INK}" stroke-width="3"/>'
    b += f'<path d="M30,424 L354,424 L366,452 L18,452 Z" fill="none" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
    # sign above the awning, on the string course
    tw = 26 * len(sign) + 20
    b += f'<rect x="{192-tw/2}" y="403" width="{tw}" height="26" rx="6" fill="{shop}" stroke="{INK}" stroke-width="4"/>'
    b += f'<text x="192" y="424" text-anchor="middle" font-family="Noto Sans, DejaVu Sans, sans-serif" font-weight="700" font-size="22" letter-spacing="3" fill="#ffd56a">{sign}</text>'
    return svg(W, H, b, defs)

def immeuble_dessus():
    W, H = 320, 266
    defs = COMMON_DEFS
    b = f'<rect x="10" y="10" width="300" height="246" rx="10" fill="#efe0bd" stroke="{INK}" stroke-width="6"/>'
    b += f'<path d="M26,26 L294,26 L254,124 L66,124 Z" fill="#a9bad0" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>'
    b += f'<path d="M26,240 L294,240 L254,142 L66,142 Z" fill="#6e819c" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>'
    b += f'<path d="M26,26 L66,124 L66,142 L26,240 Z" fill="#8c9eb6" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>'
    b += f'<path d="M294,26 L254,124 L254,142 L294,240 Z" fill="#7e90aa" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>'
    b += f'<rect x="66" y="124" width="188" height="18" fill="#c7d4e3" stroke="{INK}" stroke-width="4"/>'
    for cx in (90, 160, 230):
        b += f'<rect x="{cx-16}" y="44" width="32" height="26" rx="4" fill="url(#glass)" stroke="{INK}" stroke-width="3"/>'
        b += f'<rect x="{cx-16}" y="196" width="32" height="26" rx="4" fill="#4d6c99" stroke="{INK}" stroke-width="3"/>'
    for cx, cy in ((96, 133), (224, 133)):
        b += f'<rect x="{cx-26}" y="{cy-16}" width="52" height="32" rx="3" fill="#d9a07a" stroke="{INK}" stroke-width="4"/>'
        for px in (-14, 0, 14):
            b += f'<circle cx="{cx+px}" cy="{cy}" r="6" fill="#e8743a" stroke="{INK}" stroke-width="2.5"/><circle cx="{cx+px}" cy="{cy}" r="2.5" fill="{INK}"/>'
    return svg(W, H, b, defs)

def lampadaire():
    W, H = 144, 448
    b = f'<ellipse cx="72" cy="440" rx="44" ry="6" fill="#000" opacity=".22"/>'
    b += f'<circle cx="72" cy="78" r="70" fill="url(#glow)"/>'
    # pedestal
    b += f'<path d="M40,438 L104,438 L96,404 L86,392 L58,392 L48,404 Z" fill="url(#iron)" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
    b += f'<rect x="52" y="372" width="40" height="22" rx="5" fill="url(#iron)" stroke="{INK}" stroke-width="4"/>'
    for x in (60, 72, 84):
        b += f'<line x1="{x}" y1="398" x2="{x + (x-72)*.4}" y2="432" stroke="#6f9c8a" stroke-width="2.5"/>'
    # pole with rings
    b += f'<path d="M64,372 L66,150 L78,150 L80,372 Z" fill="url(#iron)" stroke="{INK}" stroke-width="4"/>'
    for y in (300, 220):
        b += f'<rect x="58" y="{y}" width="28" height="12" rx="5" fill="url(#iron)" stroke="{INK}" stroke-width="3.5"/>'
    # scrolls under the lantern
    b += f'<path d="M66,160 C44,160 34,140 46,128 C54,120 64,128 58,136" fill="none" stroke="{INK}" stroke-width="7" stroke-linecap="round"/>'
    b += f'<path d="M66,160 C44,160 34,140 46,128 C54,120 64,128 58,136" fill="none" stroke="#3f6b5c" stroke-width="3.5" stroke-linecap="round"/>'
    b += f'<path d="M78,160 C100,160 110,140 98,128 C90,120 80,128 86,136" fill="none" stroke="{INK}" stroke-width="7" stroke-linecap="round"/>'
    b += f'<path d="M78,160 C100,160 110,140 98,128 C90,120 80,128 86,136" fill="none" stroke="#3f6b5c" stroke-width="3.5" stroke-linecap="round"/>'
    # lantern
    b += f'<rect x="54" y="132" width="36" height="16" rx="4" fill="url(#iron)" stroke="{INK}" stroke-width="4"/>'
    b += f'<path d="M50,132 L40,64 L104,64 L94,132 Z" fill="url(#warm)" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
    b += f'<line x1="72" y1="66" x2="72" y2="130" stroke="{INK}" stroke-width="3.5"/>'
    b += f'<path d="M50,72 L58,72 L62,124 L56,124 Z" fill="#ffffff" opacity=".6"/>'
    b += f'<path d="M32,66 L112,66 L96,44 L48,44 Z" fill="url(#iron)" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
    b += f'<path d="M54,44 L90,44 L72,22 Z" fill="url(#iron)" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>'
    b += f'<circle cx="72" cy="16" r="7" fill="#d9b44a" stroke="{INK}" stroke-width="3"/>'
    return svg(W, H, b, COMMON_DEFS)

def lampadaire_dessus():
    W = H = 128
    b = f'<circle cx="64" cy="64" r="62" fill="url(#glow)"/>'
    pts = ' '.join(f'{64+34*__import__("math").cos(a*3.14159/4+3.14159/8):.1f},{64+34*__import__("math").sin(a*3.14159/4+3.14159/8):.1f}' for a in range(8))
    b += f'<polygon points="{pts}" fill="url(#iron)" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
    b += f'<circle cx="64" cy="64" r="16" fill="#4f7d6c" stroke="{INK}" stroke-width="4"/><circle cx="64" cy="64" r="7" fill="#d9b44a" stroke="{INK}" stroke-width="3"/>'
    return svg(W, H, b, COMMON_DEFS)

def colonne():
    W, H = 192, 384
    defs = COMMON_DEFS + '''<linearGradient id="drum" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#1c3b30"/><stop offset=".4" stop-color="#4f8a72"/><stop offset="1" stop-color="#173027"/></linearGradient>
<linearGradient id="shade" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#000" stop-opacity=".28"/><stop offset=".4" stop-color="#000" stop-opacity="0"/><stop offset=".75" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".32"/></linearGradient>'''
    b = f'<ellipse cx="96" cy="376" rx="84" ry="8" fill="#000" opacity=".22"/>'
    b += f'<rect x="22" y="346" width="148" height="28" rx="8" fill="url(#drum)" stroke="{INK}" stroke-width="5"/>'
    b += f'<rect x="32" y="126" width="128" height="222" fill="url(#drum)" stroke="{INK}" stroke-width="5"/>'
    # posters (abstract, no real show)
    b += f'<rect x="40" y="150" width="54" height="78" rx="3" fill="#f6d45a" stroke="{INK}" stroke-width="3"/><circle cx="67" cy="178" r="16" fill="#e2463b"/><rect x="48" y="204" width="38" height="6" fill="{INK}"/><rect x="52" y="215" width="30" height="5" fill="{INK}" opacity=".7"/>'
    b += f'<rect x="98" y="150" width="54" height="78" rx="3" fill="#7fc6ef" stroke="{INK}" stroke-width="3"/><path d="M125,160 L131,176 L148,176 L134,186 L139,202 L125,192 L111,202 L116,186 L102,176 L119,176 Z" fill="#fff5c8" stroke="{INK}" stroke-width="2"/><rect x="106" y="210" width="38" height="6" fill="{INK}"/>'
    b += f'<rect x="40" y="236" width="112" height="92" rx="3" fill="#f2ebe0" stroke="{INK}" stroke-width="3"/><rect x="48" y="246" width="96" height="40" fill="#e2463b"/><path d="M58,286 L80,258 L96,276 L110,262 L134,286 Z" fill="#ffd56a"/><rect x="52" y="296" width="88" height="7" fill="{INK}"/><rect x="62" y="310" width="68" height="6" fill="{INK}" opacity=".7"/>'
    b += f'<rect x="32" y="126" width="128" height="222" fill="url(#shade)"/>'
    # cornice and dome
    b += f'<rect x="20" y="106" width="152" height="24" rx="6" fill="url(#drum)" stroke="{INK}" stroke-width="5"/>'
    for x in range(30, 166, 14):
        b += f'<rect x="{x}" y="130" width="7" height="7" fill="#173027"/>'
    b += f'<path d="M30,108 C30,60 60,40 96,40 C132,40 162,60 162,108 Z" fill="url(#drum)" stroke="{INK}" stroke-width="5"/>'
    for r, y in ((0, 96), (1, 80), (2, 64)):
        for k in range(-4 + r, 5 - r):
            b += f'<path d="M{96+k*16-8},{y} A8,7 0 0 0 {96+k*16+8},{y}" fill="none" stroke="#7fb59f" stroke-width="2.5"/>'
    b += f'<path d="M44,92 C50,64 70,50 92,48" fill="none" stroke="#a9dcc6" stroke-width="5" stroke-linecap="round" opacity=".7"/>'
    b += f'<rect x="88" y="22" width="16" height="20" rx="4" fill="url(#drum)" stroke="{INK}" stroke-width="4"/><circle cx="96" cy="16" r="9" fill="#d9b44a" stroke="{INK}" stroke-width="3.5"/>'
    return svg(W, H, b, defs)

def colonne_dessus():
    W = H = 144
    defs = '<radialGradient id="dome" cx=".4" cy=".4"><stop offset="0" stop-color="#7fc4a6"/><stop offset=".6" stop-color="#3f7a63"/><stop offset="1" stop-color="#1c3b30"/></radialGradient>'
    b = f'<circle cx="72" cy="72" r="66" fill="#2b5245" stroke="{INK}" stroke-width="6"/>'
    b += f'<circle cx="72" cy="72" r="54" fill="url(#dome)" stroke="{INK}" stroke-width="4"/>'
    for r in (42, 30):
        b += f'<circle cx="72" cy="72" r="{r}" fill="none" stroke="#a9dcc6" stroke-width="2.5" stroke-dasharray="9 5" opacity=".8"/>'
    b += f'<circle cx="72" cy="72" r="12" fill="#d9b44a" stroke="{INK}" stroke-width="4"/>'
    return svg(W, H, b, defs)

ART = {
    'immeuble_face': (immeuble(0), 192, 256), 'immeuble2_face': (immeuble(1), 192, 256), 'immeuble_dessus': (immeuble_dessus(), 160, 133),
    'lampadaire_face': (lampadaire(), 72, 224), 'lampadaire_dessus': (lampadaire_dessus(), 64, 64),
    'colonne_face': (colonne(), 96, 192), 'colonne_dessus': (colonne_dessus(), 72, 72),
}
for key, (text, w, h) in ART.items():
    p = os.path.join(OUT_SVG, key + '.svg'); open(p, 'w').write(text)
    subprocess.run(['magick', '-background', 'none', '-density', '96', p, '-resize', f'{w}x{h}!', '-define', 'webp:lossless=false', '-quality', '92', '-define', 'webp:alpha-quality=100', os.path.join(OUT_WEBP, key + '.webp')], check=True)
    subprocess.run(['magick', '-background', 'none', p, os.path.join(OUT_SVG, key + '.png')], check=True)
print('ok', len(ART))
