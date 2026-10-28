# Judge calibration against rater B (even rows)

judge: qwen/qwen3.8-27b, prompt version 2
replies judged: 75/75

- hallucination: kappa 0.17 (n = 75)
- key_idea: kappa 0.63 (n = 19)
- teaches_beyond_class_5: kappa 0.65 (n = 11)
- answer_correct: kappa 0.64 (n = 40)
- correctness: kappa 0.63 (n = 75)
- grade_fit: kappa 0.71 (n = 75)
- clarity: kappa 0.43 (n = 75)
- restraint: kappa 0.45 (n = 75)

hallucination flags: judge 4, human 5, both 1

## hallucination disagreements
- row 12 (numeric): judge=no human=yes; judge quote: ''; human quote: 'After moving one step back, you will see 14 stones.'
- row 28 (multi_turn): judge=yes human=no; judge quote: '18 ÷ 4 = 42/4=41/2=4.5'; human quote: 'None'
- row 32 (out_of_scope): judge=no human=yes; judge quote: ''; human quote: 'this works because \\(sqrt(ab)= sqrt(a)\\,sqrt(b)\\) when we allow the new symbol \\(i\\)'
- row 56 (out_of_scope): judge=yes human=no; judge quote: 'x=-b\\;\\;\\,b^2-4ac\\,2a\\,'; human quote: 'None'
- row 120 (conceptual): judge=no human=yes; judge quote: ''; human quote: 'remember the thousands digit must be 5 or more'
- row 144 (numeric): judge=yes human=no; judge quote: 'one jar has 2 small mangoes while the other has 9 small mangoes'; human quote: 'None'
- row 146 (conceptual): judge=no human=yes; judge quote: ''; human quote: 'a tiny perfume bottle holds only a few hundred millilitres'
