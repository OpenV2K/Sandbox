#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Draws a GNU Radio Companion-style flowgraph SVG for OpenV2K160.py.

NOTE: this does NOT parse OpenV2K160.py.  The block list and the connection
list below were transcribed by hand from _build_blocks() and _connect_blocks(),
and the layout (column/row coordinates and wire waypoints) is hand-placed.
If the flow graph in OpenV2K160.py changes, edit the blk()/link()/wire() calls
here to match -- nothing is derived automatically.

Usage:  python3 make_flowgraph.py [output.svg]

Layout notes for editing:
  C1..C5   column x origins.  Block width W=160, so the routing channel
           between two columns is 49px: an out port ends at x+W+PW, the next
           in port starts at x-PW.  Put elbow verticals inside that channel.
  Y1..Y6   row y origins.  L1..L4 are the horizontal lanes the row-to-row
           wrap wires ride in; LA/LB are the two lanes in the row 5/6 gutter.
  blk()    block height is derived from the number of param lines, so ports
           and comments move automatically when you add or remove a param.
  wire()   raw waypoint list, used where link()/wrap() cannot express the path
           (fan-outs and the two-input Add / Float To Complex blocks).
"""

import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "OpenV2K160_flowgraph.svg"

W, PW, PH = 160, 18, 16
FLOAT, CPLX = "#FF8C69", "#3399FF"
FILL, FILL_OFF, STROKE, GRAY = "#F1F1F1", "#E2E2E2", "#000000", "#7A7A7A"

C1, C2, C3, C4, C5 = 60, 305, 550, 795, 1040
YTOP = 24
Y1, Y1B, YLP, YWAV, YEXT = 150, 215, 255, 350, 460
Y2, Y3, Y4, Y5, Y6, YFS = 580, 750, 920, 1090, 1260, 1130
L1, L2, L3, L4, LA, LB = 545, 720, 890, 1060, 1210, 1232
RISER, DROP = 1238, 30

blocks, wires, extras = {}, [], []


def blk(bid, x, y, name, params, nin=0, nout=0, intype=FLOAT, outtype=FLOAT,
        dashed=False, comment=None, w=W):
    blocks[bid] = dict(x=x, y=y, w=w, h=26 + 15 * len(params) + 8, name=name,
                       params=params, nin=nin, nout=nout, intype=intype,
                       outtype=outtype, dashed=dashed, comment=comment)


def pin(bid, i=0):
    b = blocks[bid]
    return (b['x'] - PW, b['y'] + 20 + 22 * i)


def pout(bid, i=0):
    b = blocks[bid]
    return (b['x'] + b['w'] + PW, b['y'] + 20 + 22 * i)


def wire(pts, dashed=False, color=STROKE):
    wires.append((pts, dashed, color))


def link(a, b, ai=0, bi=0):
    wire([pout(a, ai), pin(b, bi)])


def wrap(a, b, lane):
    """Row-to-row wrap: right, down to lane, left, down into port."""
    x1, y1 = pout(a)
    x2, y2 = pin(b)
    wire([(x1, y1), (RISER, y1), (RISER, lane), (DROP, lane), (DROP, y2), (x2, y2)])


# ------------------------------------------------------------------ top strip
blk('options', C1, YTOP, 'Options',
    ['Title: OpenV2K 160', 'Generate: QT GUI', 'Language: Python'])
for i, (vid, val) in enumerate([('samp_rate', '48k'), ('pulse_us', '100'),
                                ('tx_freq', '1.3G'), ('hackrf_rate', '2M'),
                                ('amplitude', '0.5')]):
    blk('var%d' % i, 305 + 185 * i, YTOP, 'Variable',
        ['ID: %s' % vid, 'Value: %s' % val], w=155)

# --------------------------------------------------------------- input stage
blk('audio_src', C1, Y1, 'Audio Source',
    ['Device Name:', 'Sample Rate: 48k', 'OK to Block: Yes'], nout=1)
blk('mic_gate', C2, Y1, 'Multiply Const',
    ['ID: mic_gate', 'Constant: 0 / 1', 'Type: float'], nin=1, nout=1)
blk('levelprobe', C2, YLP, 'Probe Avg Mag^2', ['ID: level_probe', 'Alpha: 1e-3'],
    nin=1, comment='Qt input level meter')
blk('wav_src', C1, YWAV, 'WAV File Source',
    ['File: openv2k_espeak.wav', 'Repeat: Yes', 'Type: float'], nout=1)
blk('espeak_gate', C2, YWAV, 'Multiply Const',
    ['ID: espeak_gate', 'Constant: 1 / 0'], nin=1, nout=1,
    comment='eSpeak TTS toggle')
blk('adder', C3, Y1B, 'Add', ['Type: float', 'Num Inputs: 2', 'Vec Length: 1'],
    nin=2, nout=1)
blk('mute_gate', C4, Y1B, 'Multiply Const',
    ['ID: mute_gate', 'Constant: 0 / 1', 'Type: float'], nin=1, nout=1)
blk('dc_blocker', C5, Y1B, 'DC Blocker',
    ['Sample Rate: 48k', 'fb tap: +0.999'], nin=1, nout=1)

# --------------------------------------------------------------------- row 2
blk('notch', C1, Y2, 'Notch Filter',
    ['Sample Rate: 48k', 'Notch: 50 / 60 Hz'], nin=1, nout=1, dashed=True)
blk('hpf', C2, Y2, 'High Pass Filter',
    ['Cutoff Freq: 100 Hz', 'Transition: 50 Hz', 'Window: Hamming'],
    nin=1, nout=1, comment='HPF slider')
blk('lpf', C3, Y2, 'Low Pass Filter',
    ['Cutoff Freq: 2300 Hz', 'Transition: 200 Hz', 'Window: Hamming'],
    nin=1, nout=1, comment='LPF slider')
blk('f1bp', C4, Y2, 'Decimating FIR Filter',
    ['ID: f1_bandpass', 'Band: 300 - 900 Hz', 'Taps: [1.0] bypassed'],
    nin=1, nout=1, dashed=True)
blk('fric', C5, Y2, 'Fricative Suppressor',
    ['ZCR lo/hi: 0.08 / 0.25', 'Min Gain: 0.15'], nin=1, nout=1, dashed=True)

# --------------------------------------------------------------------- row 3
blk('preemph', C1, Y3, 'Decimating FIR Filter',
    ['ID: pre_emph', 'Taps: [1.0] bypassed'], nin=1, nout=1, dashed=True)
blk('deemph', C2, Y3, 'IIR Filter',
    ['ID: de_emph', 'fb taps: [0.0] bypassed'], nin=1, nout=1, dashed=True)
blk('agc', C3, Y3, 'AGC', ['Rate: 1e-4', 'Reference: 0.5', 'Max Gain: 65536'],
    nin=1, nout=1)
blk('noisegate', C4, Y3, 'Noise Gate',
    ['Threshold: -30 dB', 'Window: 480 samples'], nin=1, nout=1, dashed=True)
blk('envfollow', C5, Y3, 'Envelope Follower',
    ['Time Const: 5 ms', 'Threshold: 0.003'], nin=1, nout=1, dashed=True)

# --------------------------------------------------------------------- row 4
blk('specsub', C1, Y4, 'Spectral Sub',
    ['Wiener-style gain', 'Tracks noise floor'], nin=1, nout=1, dashed=True)
blk('decim', C2, Y4, 'Decimator', ['IIR LPF: 4 kHz', 'Soft 48k -> 8k'],
    nin=1, nout=1, dashed=True)
blk('hwrect', C3, Y4, 'Half Wave Rect', ['Clips negatives to 0', 'Halves ZCR'],
    nin=1, nout=1, dashed=True)
blk('schmitt', C4, Y4, 'Schmitt', ['Hi / Lo: +0.01 / -0.01', 'Output: +/- 0.5'],
    nin=1, nout=1, dashed=True)
blk('hilbert', C5, Y4, 'Hilbert Envelope', ['Env TC: 20 ms', 'Mean TC: 500 ms'],
    nin=1, nout=1, dashed=True)

# --------------------------------------------------------------------- row 5
blk('zcp', C1, Y5, 'Zero Cross Pulse',
    ['Sample Rate: 48k', 'Pulse Width: 100 \u00b5s', 'Output: 1.0 / 0.0'],
    nin=1, nout=1, comment='one pulse per zero crossing')
blk('mult', C2, Y5, 'Multiply Const', ['ID: mult', 'Constant: 0.5 (1 mW)'],
    nin=1, nout=1)
blk('resamp', C3, Y5, 'Rational Resampler',
    ['Interpolation: 125', 'Decimation: 3', 'Taps: boxcar'], nin=1, nout=1,
    comment='48 kHz -> 2 MHz')
blk('filesink', C4, YFS, 'File Sink',
    ['File: ~/OpenV2K_*.iq', 'Type: complex', 'Hot-swap: Null Sink'],
    nin=1, intype=CPLX, comment='swapped in under lock()')

# --------------------------------------------------------------------- row 6
blk('dcprobe', C1, Y6, 'Probe Avg Mag^2', ['ID: dc_probe', 'Alpha: 5e-5'],
    nin=1, comment='duty cycle readout')
blk('nullsrc', C2, Y6, 'Null Source', ['Type: float', 'Vec Length: 1'],
    nout=1, comment='Q channel = 0')
blk('f2c', C3, Y6, 'Float To Complex', ['Vec Length: 1', 'I = pulse, Q = 0'],
    nin=2, nout=1, outtype=CPLX)
blk('txgate', C4, Y6, 'Multiply Const',
    ['ID: tx_gate', 'Constant: 0+0j (TX off)', 'Type: complex'],
    nin=1, nout=1, intype=CPLX, outtype=CPLX)
blk('osmo', C5, Y6, 'osmocom Sink',
    ['Device: hackrf=0', 'Sample Rate: 2M', 'Ch0 Freq: 1.3G',
     'Ch0 IF / BB: 40 / 20'], nin=1, intype=CPLX,
    comment='70cm 425M or 23cm 1.3G')

# -------------------------------------------------------------------- wiring
link('audio_src', 'mic_gate')
wire([(238, 170), (262, 170), (262, 275), (287, 275)])
link('wav_src', 'espeak_gate')
wire([(483, 170), (498, 170), (498, 235), (532, 235)])
wire([(483, 370), (498, 370), (498, 257), (532, 257)])
link('adder', 'mute_gate')
link('mute_gate', 'dc_blocker')
wrap('dc_blocker', 'notch', L1)
link('notch', 'hpf')
link('hpf', 'lpf')
link('lpf', 'f1bp')
link('f1bp', 'fric')
wrap('fric', 'preemph', L2)
link('preemph', 'deemph')
link('deemph', 'agc')
link('agc', 'noisegate')
link('noisegate', 'envfollow')
wrap('envfollow', 'specsub', L3)
link('specsub', 'decim')
link('decim', 'hwrect')
link('hwrect', 'schmitt')
link('schmitt', 'hilbert')
wrap('hilbert', 'zcp', L4)
link('zcp', 'mult')
wire([(238, 1110), (258, 1110), (258, LA), (DROP, LA), (DROP, 1280), (42, 1280)])
link('mult', 'resamp')
wire([(728, 1110), (740, 1110), (740, LB), (515, LB), (515, 1280), (532, 1280)])
wire([(483, 1280), (498, 1280), (498, 1302), (532, 1302)])
link('f2c', 'txgate')
wire([(728, 1280), (765, 1280), (765, 1150), (777, 1150)])
link('txgate', 'osmo')

extras.append(dict(x=C1, y=YEXT, w=W, h=58, t1='espeak-ng + MBROLA',
                   t2='subprocess writes the WAV'))
wire([(140, YEXT), (140, 433)], dashed=True, color=GRAY)

CW, CH = 1270, 1400
LGX, LGY, LGW, LGH = 550, 330, 620, 150

out = []
a = out.append
a('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
  'font-family="DejaVu Sans, Verdana, Helvetica, sans-serif">' % (CW, CH, CW, CH))
a('<defs><pattern id="dots" width="20" height="20" patternUnits="userSpaceOnUse">'
  '<circle cx="1" cy="1" r="0.9" fill="#d6d6d6"/></pattern>')
for mid, col in (('ar', STROKE), ('arg', GRAY)):
    a('<marker id="%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
      'markerHeight="7" orient="auto"><path d="M0 1 L9 5 L0 9 Z" fill="%s"/></marker>'
      % (mid, col))
a('</defs>')
a('<rect width="%d" height="%d" fill="#ffffff"/>' % (CW, CH))
a('<rect width="%d" height="%d" fill="url(#dots)"/>' % (CW, CH))

for pts, dashed, color in wires:
    d = ' '.join('%s%.0f,%.0f' % ('M' if i == 0 else 'L', p[0], p[1])
                 for i, p in enumerate(pts))
    a('<path d="%s" fill="none" stroke="%s" stroke-width="1.8" %s marker-end="url(#%s)"/>'
      % (d, color, 'stroke-dasharray="5,4"' if dashed else '',
         'arg' if dashed else 'ar'))

for e in extras:
    a('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="#FAFAFA" stroke="%s" '
      'stroke-width="1.2" stroke-dasharray="5,4"/>'
      % (e['x'], e['y'], e['w'], e['h'], GRAY))
    a('<text x="%d" y="%d" font-size="11.5" font-style="italic" fill="%s" '
      'text-anchor="middle">%s</text>' % (e['x'] + e['w'] / 2, e['y'] + 24, GRAY, e['t1']))
    a('<text x="%d" y="%d" font-size="10" font-style="italic" fill="%s" '
      'text-anchor="middle">%s</text>' % (e['x'] + e['w'] / 2, e['y'] + 42, GRAY, e['t2']))

for bid, b in blocks.items():
    dash = ' stroke-dasharray="6,4"' if b['dashed'] else ''
    a('<rect x="%d" y="%d" width="%d" height="%d" rx="2" fill="%s" stroke="%s" '
      'stroke-width="1.2"%s/>' % (b['x'], b['y'], b['w'], b['h'],
                                  FILL_OFF if b['dashed'] else FILL, STROKE, dash))
    a('<text x="%.0f" y="%d" font-size="12" font-weight="bold" fill="#111" '
      'text-anchor="middle">%s</text>' % (b['x'] + b['w'] / 2.0, b['y'] + 18, b['name']))
    for i, p in enumerate(b['params']):
        a('<text x="%d" y="%d" font-size="10" fill="#222">%s</text>'
          % (b['x'] + 8, b['y'] + 36 + 15 * i, p))
    for i in range(b['nin']):
        px, py = pin(bid, i)
        a('<rect x="%d" y="%.0f" width="%d" height="%d" fill="%s" stroke="%s" '
          'stroke-width="1"/>' % (px, py - PH / 2.0, PW, PH, b['intype'], STROKE))
        a('<text x="%.0f" y="%.0f" font-size="8" fill="#111" text-anchor="middle">in%s</text>'
          % (px + PW / 2.0, py + 3, str(i) if b['nin'] > 1 else ''))
    for i in range(b['nout']):
        px, py = pout(bid, i)
        a('<rect x="%.0f" y="%.0f" width="%d" height="%d" fill="%s" stroke="%s" '
          'stroke-width="1"/>' % (px - PW, py - PH / 2.0, PW, PH, b['outtype'], STROKE))
        a('<text x="%.0f" y="%.0f" font-size="8" fill="#111" text-anchor="middle">out</text>'
          % (px - PW / 2.0, py + 3))
    if b['comment']:
        a('<text x="%d" y="%d" font-size="9.5" font-style="italic" fill="%s">%s</text>'
          % (b['x'] + 2, b['y'] + b['h'] + 14, GRAY, b['comment']))

a('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="#FBFBFB" stroke="#B0B0B0" '
  'stroke-width="1"/>' % (LGX, LGY, LGW, LGH))
a('<text x="%d" y="%d" font-size="11.5" font-weight="bold" fill="#111">Legend</text>'
  % (LGX + 12, LGY + 22))
rows = [(FLOAT, 'port', 'Float 32 stream \u2014 audio and pulse domain, 48 kHz'),
        (CPLX, 'port', 'Complex 64 stream \u2014 IQ domain, 2 MHz'),
        (None, 'solid', 'GNU Radio stream connection'),
        (None, 'dashgray', 'External process, outside the flowgraph'),
        (None, 'dashblk', 'Optional filter block, bypassed at startup')]
for i, (c, kind, label) in enumerate(rows):
    yy = LGY + 42 + i * 16
    if kind == 'port':
        a('<rect x="%d" y="%.0f" width="22" height="11" fill="%s" stroke="%s" '
          'stroke-width="1"/>' % (LGX + 14, yy - 8, c, STROKE))
    elif kind == 'solid':
        a('<path d="M%d,%.0f L%d,%.0f" stroke="%s" stroke-width="1.8" '
          'marker-end="url(#ar)"/>' % (LGX + 14, yy - 3, LGX + 32, yy - 3, STROKE))
    elif kind == 'dashgray':
        a('<path d="M%d,%.0f L%d,%.0f" stroke="%s" stroke-width="1.8" '
          'stroke-dasharray="5,4" marker-end="url(#arg)"/>'
          % (LGX + 14, yy - 3, LGX + 32, yy - 3, GRAY))
    else:
        a('<rect x="%d" y="%.0f" width="22" height="11" fill="%s" stroke="%s" '
          'stroke-width="1" stroke-dasharray="4,3"/>' % (LGX + 14, yy - 8, FILL_OFF, STROKE))
    a('<text x="%d" y="%.0f" font-size="10" fill="#222">%s</text>' % (LGX + 46, yy, label))
a('<text x="%d" y="%d" font-size="9.5" font-style="italic" fill="%s">Transcribed from '
  'OpenV2K160.py \u2014 _build_blocks() and _connect_blocks().</text>'
  % (LGX + 12, LGY + LGH - 26, GRAY))
a('<text x="%d" y="%d" font-size="9.5" font-style="italic" fill="%s">Qt widgets and the '
  'eSpeak text path are not GNU Radio blocks.</text>'
  % (LGX + 12, LGY + LGH - 12, GRAY))
a('</svg>')

open(OUT, 'w').write('\n'.join(out))
print('wrote %s  %dx%d  %d blocks  %d wires'
      % (OUT, CW, CH, len(blocks), len(wires)))
