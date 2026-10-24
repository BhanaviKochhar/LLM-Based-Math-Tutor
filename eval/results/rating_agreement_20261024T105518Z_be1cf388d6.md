# Human rating quality and agreement

## rater A
- blank cells: 0; most common value share per rubric column: {'correctness': 0.87, 'grade_fit': 0.62, 'clarity': 0.49, 'restraint': 0.4}
- 'answer correct?' agrees with the code's verdict on 54/56 numeric replies
- contradictions (correct = No but correctness 5): [9, 64, 80, 112]
- hallucination flags: 9; flags without a quote: none

## rater B
- blank cells: 0; most common value share per rubric column: {'correctness': 0.81, 'grade_fit': 0.43, 'clarity': 0.47, 'restraint': 0.35}
- 'answer correct?' agrees with the code's verdict on 55/56 numeric replies
- contradictions (correct = No but correctness 5): none
- hallucination flags: 8; flags without a quote: none

## agreement between the raters (Cohen's kappa; rubric: quadratic-weighted)
- correct: 0.92
- key_idea: 0.95
- teaches: 0.96
- halluc: 0.69
- correctness: 0.52
- grade_fit: 0.82
- clarity: 0.74
- restraint: 0.84

## rows where the raters disagree on hallucination
- row 12: A=No, B=Yes; quote: After moving one step back, you will see 14 stones.
- row 26: A=Yes, B=No; quote: 1,03,33,32
- row 32: A=No, B=Yes; quote: this works because \(sqrt(ab)= sqrt(a)\,sqrt(b)\) when we allow the new symbol \(i\)
- row 41: A=Yes, B=No; quote: the map tells us that 4 cm on the map = 2 km on the ground
- row 123: A=Yes, B=No; quote: | | | 5 | . | 0 | 5 |
