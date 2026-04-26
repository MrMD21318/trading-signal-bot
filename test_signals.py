import sys
sys.path.insert(0, ".")
from run_us100_monitor import get_candles, analyze_candles_1m, analyze_candles_5m, analyze_candles_15m

m1 = get_candles("1", 60)
m5 = get_candles("5", 40)
m15 = get_candles("15", 20)

print(f"Candles: 1M={len(m1)}, 5M={len(m5)}, 15M={len(m15)}")
if m5:
    print(f"Price: {m5[0][4]:.1f}")

print()

s1 = analyze_candles_1m(m1)
print(f"--- 1M signals: {len(s1)} ---")
for s in s1:
    print(f"  {s['direction']:6s} {s['setup']:25s} E={s['entry']:<10.1f} SL={s['sl']:<10.1f} TP={s['tp']}")

s5 = analyze_candles_5m(m5, m1)
print(f"--- 5M signals: {len(s5)} ---")
for s in s5:
    print(f"  {s['direction']:6s} {s['setup']:25s} E={s['entry']:<10.1f} SL={s['sl']:<10.1f} TP={s['tp']}")

s15 = analyze_candles_15m(m15)
print(f"--- 15M signals: {len(s15)} ---")
for s in s15:
    print(f"  {s['direction']:6s} {s['setup']:25s} E={s['entry']:<10.1f} SL={s['sl']:<10.1f} TP={s['tp']}")

total = len(s1) + len(s5) + len(s15)
print(f"\nTotal signals: {total}")
