# Scope decision validation (word rules + small model)

model: openai/gpt-oss-20b, params: {'temperature': 0.0, 'max_tokens': 600, 'top_p': 1.0, 'reasoning_effort': 'medium'}

- curriculum: in-scope wrongly stopped 7/935; out-of-scope stopped 0/0; model calls 906 for 935 messages
- out_of_scope: in-scope wrongly stopped 0/60; out-of-scope stopped 194/198 (disguised 45/49); model calls 79 for 277 messages
- multi_turn new problems: in-scope wrongly stopped 1/253; out-of-scope stopped 19/19; model calls 188 for 275 messages
- held-out child-style openers: in-scope wrongly stopped 0/30; out-of-scope stopped 0/0; model calls 30 for 30 messages
- held-out ambiguous/everyday: in-scope wrongly stopped 0/20; out-of-scope stopped 0/0; model calls 20 for 20 messages
- held_out_out_of_scope: in-scope wrongly stopped 0/10; out-of-scope stopped 33/40 (disguised 33/40); model calls 46 for 50 messages

## errors
- cb-338 expect=in_scope got=refuse: Why does 8 minus 3 give a sensible answer, while 3 minus 8 would not make sense yet at this level?
- cb-473 expect=in_scope got=refuse: I think subtracting a bigger 2-digit number from a smaller one just gives 0.

What happens if you try to subtr
- cb-547 expect=in_scope got=refuse: I think you can divide 9 by 0 and just get 9 back, since dividing by 0 shouldn't change anything.

What is 9 d
- cb-686 expect=in_scope got=refuse: What do we call a straight line that touches a circle's edge at exactly one point?
- cb-757 expect=in_scope got=refuse: I think a tangent line crosses through the inside of a circle on its way past.

Does a tangent line cross thro
- cb-892 expect=in_scope got=refuse: I think a reflex angle is just a bigger version of an obtuse angle.

Is a reflex angle simply a bigger obtuse 
- cb-924 expect=in_scope got=refuse: I think a cube with double the edge length of a smaller cube has exactly double the volume.

Does doubling a c
- oos-051 expect=stop got=pass: If I know how fast a tap is dripping at every single second, how do I work out the total water collected over 
- oos-107 expect=stop got=pass: A jar has 4 yellow and 6 green marbles mixed together -- if I grab one with my eyes closed, out of 10 tries ab
- oos-115 expect=stop got=pass: Among these 9 recorded daily temperatures, which single value has exactly as many readings above it as below i
- oos-171 expect=stop got=pass: I have two labelled quantities, one called 'first' and one called 'second' -- if I add them and then square th
- mt-143#t3 expect=in_scope got=refuse: What if the perimeter was 26 but the length was 7 instead -- what would the width be?
- ho-oos-04 expect=stop got=pass: Ravi has 3 marbles for every 5 that Meena has. Meena has 2 marbles for every 3 that Seema has. Together the th
- ho-oos-05 expect=stop got=pass: One tap can fill a tank in 6 hours. Another tap can fill the same tank in 4 hours. If both taps are opened tog
- ho-oos-06 expect=stop got=pass: A round pizza that is 20 cm wide is just enough for 4 children. How wide must a round pizza be to be just enou
- ho-oos-17 expect=stop got=pass: What is 5 take away minus 3? My brother says the answer is 8.
- ho-oos-18 expect=stop got=pass: A line on a grid goes through the spot 2 across and 1 up, and the spot 6 across and 9 up. At what across numbe
- ho-oos-20 expect=stop got=pass: On a grid, the rule is 'up is the across number times itself'. If across numbers can be on both the left and t
- ho-oos-27 expect=stop got=pass: In my class of 50 children, 30 like cricket, 25 like football and 20 like kabaddi. 12 like cricket and footbal
