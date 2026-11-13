# Final-answer scoring -- multi_turn.json

## baseline
- overall: 84/121 correct (69.4%), 95% CI [60.7%, 76.9%]; strict (correct / all 206): 40.8%; 85 not yet scorable (0 await LLM extraction, 0 await the judge)
  - grade_1: 12/12 (100.0%), strict 57.1%
  - grade_2: 11/18 (61.1%), strict 30.6%
  - grade_3: 23/29 (79.3%), strict 51.1%
  - grade_4: 22/32 (68.8%), strict 47.8%
  - grade_5: 16/30 (53.3%), strict 27.6%

## system
- overall: 39/64 correct (60.9%), 95% CI [48.7%, 71.9%]; strict (correct / all 206): 18.9%; 142 not yet scorable (0 await LLM extraction, 0 await the judge)
  - grade_1: 2/3 (66.7%), strict 9.5%
  - grade_2: 13/16 (81.2%), strict 36.1%
  - grade_3: 6/13 (46.2%), strict 13.3%
  - grade_4: 10/19 (52.6%), strict 21.7%
  - grade_5: 8/13 (61.5%), strict 13.8%

## paired (items scorable in both conditions)
- overall: n = 50, only system right = 9, only baseline right = 13, difference -8.0 pts [-25.6, +10.3], McNemar p = 0.5235
- grade_1: n = 3, only system right = 0, only baseline right = 1, difference -33.3 pts [-79.2, +29.1], McNemar p = 1.0000, Holm p = 1.0000
- grade_2: n = 13, only system right = 6, only baseline right = 3, difference +23.1 pts [-20.5, +57.8], McNemar p = 0.5078, Holm p = 1.0000
- grade_3: n = 10, only system right = 0, only baseline right = 4, difference -40.0 pts [-67.6, +0.2], McNemar p = 0.1250, Holm p = 0.6250
- grade_4: n = 15, only system right = 1, only baseline right = 3, difference -13.3 pts [-38.3, +14.3], McNemar p = 0.6250, Holm p = 1.0000
- grade_5: n = 9, only system right = 2, only baseline right = 2, difference +0.0 pts [-38.6, +38.6], McNemar p = 1.0000, Holm p = 1.0000

