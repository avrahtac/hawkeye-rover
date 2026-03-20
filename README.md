#  hawkeye-rover

> Autonomous runway surveillance rover that detects foreign object debris (FOD) in real time and transmits GPS-tagged alerts via GSM.

---

## what it does

hawkeye-rover patrols airport runway surfaces autonomously. when its camera spots debris — a tool, stone, wildlife, or any foreign object — it stops, draws a detection box on the live feed, and fires an SMS alert with the exact GPS coordinates to ground control. no human in the loop.

```
no debris  →  rover patrols forward
debris found  →  rover stops + green box on screen + SMS with GPS link
debris cleared  →  rover resumes patrol
```

---

As a part of curriculum Semester VI Mini Project, Department of Electronics and Computer Engineering, Pune University
