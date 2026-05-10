#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
ROOT = Path(__file__).resolve().parents[1]

def font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for p in candidates:
        if Path(p).exists(): return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def money(v): return f"${float(v):,.0f}"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--report', default=str(ROOT/'out/weekly_report.json'))
    ap.add_argument('--out', default=str(ROOT/'docs/assets/weekly-report-snapshot.png'))
    args=ap.parse_args()
    report=json.loads(Path(args.report).read_text())
    img=Image.new('RGB',(1400,900),'#0f172a')
    d=ImageDraw.Draw(img)
    title=font(44, True); h=font(28, True); t=font(22); small=font(18)
    d.text((48,42),'Weekly Business Report',fill='#f8fafc',font=title)
    d.text((50,98),f"{report['period']['from']} → {report['period']['to']}",fill='#94a3b8',font=t)
    cards=[('Leads',report['summary']['total_leads']),('Clean leads',report['summary']['clean_leads']),('Active deals',report['summary']['active_deals']),('Won',report['summary']['won_deals']),('Revenue',money(report['summary']['revenue']))]
    x=48
    for label,val in cards:
        d.rounded_rectangle((x,160,x+235,285),radius=22,fill='#111827',outline='#1f2937')
        d.text((x+24,182),str(val),fill='#60a5fa',font=h)
        d.text((x+24,235),label,fill='#94a3b8',font=small)
        x+=258
    y=340
    d.text((48,y),'Managers',fill='#f8fafc',font=h); y+=55
    for row in report['managers']:
        d.rounded_rectangle((48,y,660,y+78),radius=16,fill='#111827',outline='#1f2937')
        d.text((70,y+16),row['manager'],fill='#e5e7eb',font=t)
        d.text((250,y+16),f"{row['clean_leads']} leads · {row['active_deals']} deals · {row['won_deals']} wins · {money(row['revenue'])}",fill='#cbd5e1',font=small)
        y+=94
    y=340
    d.text((760,y),'Rooms / Halls',fill='#f8fafc',font=h); y+=55
    for row in report['halls']:
        d.rounded_rectangle((760,y,1240,y+78),radius=16,fill='#111827',outline='#1f2937')
        d.text((782,y+16),row['hall'],fill='#e5e7eb',font=t)
        d.text((980,y+16),f"{row['won_deals']} wins · {money(row['revenue'])}",fill='#cbd5e1',font=small)
        y+=94
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True); img.save(out); print(out)
if __name__=='__main__': main()
