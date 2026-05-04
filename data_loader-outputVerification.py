from src.data_loader import load_documents

docs = load_documents()

print(len(docs))          # ~15
print(docs[0].file_name)  # cemm101.pdf
print(docs[0].page_count) # > 0
print(docs[0].raw_text[:100]) # readable text