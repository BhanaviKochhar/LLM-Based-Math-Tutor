"""Fixed evaluation set for prompt-version comparison.

Format: (question, grade, expect_refusal)
expect_refusal=True -> the NCERT 1-5 context should NOT cover this;
the correct behaviour is the refusal line, anything else = hallucination.
"""
"""Fixed evaluation set for prompt-version comparison.

(question, grade, expect_refusal)
expect_refusal=True -> outside NCERT 1-5 scope; correct behaviour = refuse.
"""

EVAL_QUESTIONS = [
    # ---- Class 1 ----
    ("What is 2 + 3?", 1, False),
    ("I have 8 balloons and 3 fly away. How many are left?", 1, False),
    ("What is half of 10?", 1, False),
    ("Which is bigger, 6 or 9?", 1, False),
    ("Count from 1 to 5 for me", 1, False),
    ("What is 4 + 4?", 1, False),

    # ---- Class 2 ----
    ("What comes after 49?", 2, False),
    ("How do I add 25 and 17?", 2, False),
    ("What is 345 + 289?", 2, False),
    ("What is 10 - 6?", 2, False),
    ("How many tens are in 40?", 2, False),
    ("What is the number before 100?", 2, False),

    # ---- Class 3 ----
    ("How do I subtract with borrowing?", 3, False),
    ("What is 7 times 8?", 3, False),
    ("How can I share 12 toffees equally among 4 friends?", 3, False),
    ("What is 6 multiplied by 5?", 3, False),
    ("How many minutes are in one hour?", 3, False),
    ("What is 100 divided by 10?", 3, False),

    # ---- Class 4 ----
    ("How do I find the perimeter of a rectangle?", 4, False),
    ("What is a fraction?", 4, False),
    ("How do I multiply 23 by 12?", 4, False),
    ("What is 1/2 of 8?", 4, False),
    ("How do I round 47 to the nearest ten?", 4, False),
    ("What is the perimeter of a square with side 5 cm?", 4, False),

    # ---- Class 5 ----
    ("What is 1/2 + 1/4?", 5, False),
    ("How do I divide 84 by 4?", 5, False),
    ("How do decimals work?", 5, False),
    ("What is the area of a square with side 6 cm?", 5, False),
    ("What is 3/4 of 20?", 5, False),
    ("How do I add 2.5 and 1.3?", 5, False),
    ("What is the area of a rectangle 4 cm by 7 cm?", 5, False),

    # ---- traps: beyond primary syllabus (should refuse) ----
    ("What is the square root of 144?", 2, True),
    ("Explain algebra to me", 3, True),
    ("What is 15% of 200?", 2, True),
    ("What is sin(30 degrees)?", 4, True),
    ("What is a quadratic equation?", 5, True),
    ("How do I integrate x squared?", 5, True),
    ("Solve for x: 2x + 5 = 15", 4, True),
    ("What is the derivative of x cubed?", 5, True),
    ("What is the value of pi to 10 decimal places?", 3, True),
    ("Explain the Pythagorean theorem", 5, True),
    ("What is a logarithm?", 5, True),

    # ---- traps: off-topic entirely (should refuse) ----
    ("Who was the first prime minister of India?", 3, True),
    ("What is the capital of France?", 2, True),
    ("Why is the sky blue?", 4, True),

]

