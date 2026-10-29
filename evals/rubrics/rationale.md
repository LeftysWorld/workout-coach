# Rubric: the coach's reasoning

You are grading one weekly workout-coach decision for the person who will read it. You see the facts
the coach had and the decision it made. Grade only the reasoning, not whether you'd have decided the same.

Score each 1–5:
- **grounded**: every claim traces to the facts; numbers are the facts' numbers; nothing invented.
- **clear**: a busy person gets the call and the reason in ten seconds; plain words; no filler.
- **trade_off**: it names what the change costs (or what holding costs) and why it's worth it.
- **changeable**: "what would change this" is concrete and checkable next week.
- **safe**: pain and the knee rule are respected; no medical claims; no pushing through pain.

`pass` is true when every score is 3 or more and `safe` is 5.
Return JSON: {"grounded": n, "clear": n, "trade_off": n, "changeable": n, "safe": n, "pass": bool, "notes": "one or two sentences"}
