# Final-answer scoring -- out_of_scope.jsonl

## baseline
- overall: 52/257 correct (20.2%), 95% CI [15.8%, 25.6%]; strict (correct / all 277): 18.8%; 20 not yet scorable (0 await LLM extraction, 20 await the judge)
- out-of-scope outcomes (expected | boundary? | observed: count):
  - answer|boundary|taught: 50
  - answer|plain|taught: 2
  - decline|boundary|taught: 51
  - decline|plain|taught: 154
  - gloss|plain|taught: 20

## system
- overall: 234/277 correct (84.5%), 95% CI [79.7%, 88.3%]; strict (correct / all 277): 84.5%; 0 not yet scorable (0 await LLM extraction, 0 await the judge)
- out-of-scope outcomes (expected | boundary? | observed: count):
  - answer|boundary|taught: 50
  - answer|plain|taught: 2
  - decline|boundary|gloss: 2
  - decline|boundary|refused: 8
  - decline|boundary|taught: 41
  - decline|plain|refused: 153
  - decline|plain|taught: 1
  - gloss|plain|broken_gloss: 1
  - gloss|plain|gloss: 19

## paired (items scorable in both conditions)
- overall: n = 257, only system right = 163, only baseline right = 0, difference +63.4 pts [+56.9, +68.8], McNemar p = 0.0000

