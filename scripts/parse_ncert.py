import fitz
import json
import os
import re
print("started")
all_c=[]
for g in range(1,6):
    path="data/raw_pdfs/class"+str(g)+".pdf"
    doc=fitz.open(path)
    print("grade",g,"pages",len(doc))
    for pn,page in enumerate(doc):
        raw=page.get_text()
        lines=[l.strip() for l in raw.split("\n") if l.strip() and not l.strip().isdigit() and len(l.strip())>11]
        text=" ".join(lines)
        sents=re.split(r"(?<=[.!?])\s+",text)
        sents=[s for s in sents if len(s)>20]
        for i in range(0,len(sents),3):
            ch=" ".join(sents[i:i+3])
            if len(ch)>50:
                all_c.append({"text":ch,"grade":g,"page":pn+1,"source":"NCERT"})
    print("chunks so far",len(all_c))
os.makedirs("data/extracted_json",exist_ok=True)
with open("data/extracted_json/ncert_chunks.json","w",encoding="utf-8") as f:
    json.dump(all_c,f,indent=2,ensure_ascii=False)
print("DONE total chunks",len(all_c))