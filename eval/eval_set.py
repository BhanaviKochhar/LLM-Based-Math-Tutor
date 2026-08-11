"""eval/eval_set.py — evaluation questions for Objective 3.

Each item: q (question), grade, truth (a sympy-evaluable arithmetic string that
is the CORRECT answer), cat (category, for per-category reporting).

Categories are chosen to span where bare LLMs are known to fail (from the
literature): single-step is a control where baseline should do fine; large
numbers, multi-step, and distractor problems are where a bare model slips while
the injected system stays correct. Fraction/remainder items exercise the
injection gate and the remainder path.

`truth` for a distractor problem is ONLY the relevant operation — the irrelevant
numbers are the trap. Extend freely; keep truth strings arithmetic-only.
"""

EVAL_SET = [
    # -- control: easy single-step (baseline should ace these) --------------
    {"q": "What is 7 times 8?", "grade": 3, "truth": "7*8", "cat": "single-step"},
    {"q": "I have 8 balloons and 3 fly away. How many are left?", "grade": 1, "truth": "8-3", "cat": "single-step"},
    {"q": "What is 27 plus 15?", "grade": 2, "truth": "27+15", "cat": "single-step"},
    {"q": "How can I share 12 toffees equally among 4 friends?", "grade": 2, "truth": "12/4", "cat": "single-step"},
    {"q": "What comes after 49?", "grade": 1, "truth": "49+1", "cat": "single-step"},
    {"q": "A pencil costs 6 rupees. How much do 7 pencils cost?", "grade": 3, "truth": "6*7", "cat": "single-step"},

    # -- large / messy numbers (carrying, multi-digit multiply) -------------
    {"q": "What is 348 plus 276?", "grade": 5, "truth": "348+276", "cat": "large-number"},
    {"q": "What is 1000 minus 367?", "grade": 5, "truth": "1000-367", "cat": "large-number"},
    {"q": "What is 47 times 23?", "grade": 5, "truth": "47*23", "cat": "large-number"},
    {"q": "What is 63 multiplied by 48?", "grade": 5, "truth": "63*48", "cat": "large-number"},
    {"q": "Add 256, 389 and 147.", "grade": 5, "truth": "256+389+147", "cat": "large-number"},
    {"q": "What is 900 minus 458?", "grade": 4, "truth": "900-458", "cat": "large-number"},
    {"q": "What is 84 times 36?", "grade": 5, "truth": "84*36", "cat": "large-number"},
    {"q": "What is 725 minus 268?", "grade": 4, "truth": "725-268", "cat": "large-number"},

    # -- multi-step word problems -------------------------------------------
    {"q": "A shop has 7 boxes with 8 pencils each. It sells 19 pencils. How many pencils are left?", "grade": 4, "truth": "7*8-19", "cat": "multi-step"},
    {"q": "Ravi buys 3 notebooks at 24 rupees each and pays with a 100 rupee note. How much change does he get?", "grade": 5, "truth": "100-3*24", "cat": "multi-step"},
    {"q": "A tank has 60 litres. 15 litres are used in the morning and 22 in the evening. How much is left?", "grade": 4, "truth": "60-15-22", "cat": "multi-step"},
    {"q": "There are 5 rows of 6 chairs. 8 chairs are broken. How many good chairs are there?", "grade": 4, "truth": "5*6-8", "cat": "multi-step"},
    {"q": "A baker makes 96 cookies and packs them equally into 8 boxes. How many cookies per box?", "grade": 4, "truth": "96/8", "cat": "multi-step"},
    {"q": "Sita has 45 stickers. She gives 12 to a friend and buys 20 more. How many does she have now?", "grade": 3, "truth": "45-12+20", "cat": "multi-step"},
    {"q": "A bus has 40 seats. 27 are taken, then 9 people get off. How many seats are empty?", "grade": 4, "truth": "40-27+9", "cat": "multi-step"},
    {"q": "A teacher buys 9 packs of 6 pens and gives one pen to each of 32 students. How many pens are left?", "grade": 5, "truth": "6*9-32", "cat": "multi-step"},
    {"q": "A garden has 8 rows of 7 plants. Half of them are roses. How many roses are there?", "grade": 5, "truth": "(8*7)/2", "cat": "multi-step"},
    {"q": "Three friends share 84 rupees equally. How much does each friend get?", "grade": 4, "truth": "84/3", "cat": "multi-step"},

    # -- distractor numbers (irrelevant values to trap the model) -----------
    {"q": "Ravi has 12 marbles and his sister has 5. Ravi is 8 years old. How many marbles do they have together?", "grade": 2, "truth": "12+5", "cat": "distractor"},
    {"q": "A book has 200 pages and costs 150 rupees. Meena reads 45 pages on Monday and 38 on Tuesday. How many pages has she read?", "grade": 4, "truth": "45+38", "cat": "distractor"},
    {"q": "A class has 30 students and is on the 3rd floor. 18 of the students are girls. How many boys are there?", "grade": 3, "truth": "30-18", "cat": "distractor"},
    {"q": "A farmer is 54 years old. He has 6 cows and 9 goats. How many animals does he have?", "grade": 2, "truth": "6+9", "cat": "distractor"},
    {"q": "Tickets cost 20 rupees each. Anil has 3 friends and buys 4 tickets. How much does he pay?", "grade": 4, "truth": "20*4", "cat": "distractor"},
    {"q": "A jug holds 5 litres and is filled 7 times a day for 30 days. How many litres are used in one day?", "grade": 4, "truth": "5*7", "cat": "distractor"},
    {"q": "There are 8 red and 6 blue balloons at a party with 25 guests. How many balloons are there?", "grade": 2, "truth": "8+6", "cat": "distractor"},

    # -- fractions & remainder (injection gate + remainder path) ------------
    {"q": "What is 1/2 + 1/4?", "grade": 4, "truth": "1/2+1/4", "cat": "fraction"},
    {"q": "What is 3/4 minus 1/4?", "grade": 4, "truth": "3/4-1/4", "cat": "fraction"},
    {"q": "What is 1/3 of 9?", "grade": 4, "truth": "(1/3)*9", "cat": "fraction"},
    {"q": "What is 45 divided by 8?", "grade": 4, "truth": "45/8", "cat": "remainder"},
    {"q": "Share 50 toffees among 7 children equally. How many does each get?", "grade": 3, "truth": "50/7", "cat": "remainder"},
]