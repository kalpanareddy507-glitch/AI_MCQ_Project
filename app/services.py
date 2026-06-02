import os
import re
import random
import spacy
from typing import List, Dict, Any
from transformers import pipeline
import nltk
from nltk.corpus import wordnet

try:
    wordnet.ensure_loaded()
except LookupError:
    nltk.download('wordnet')
    nltk.download('omw-1.4')

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    os.system("python -m spacy download en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

class QuestionGenerationModel:
    _instance = None

    @classmethod
    def get_pipeline(cls):
        if cls._instance is None:
            print("INFO: Loading Hugging Face t5-small pipeline...")
            cls._instance = pipeline(
                "text2text-generation",
                model="t5-small",
                device=-1  # Explicit CPU utilization
            )
            print("INFO: Transformers pipeline initialized successfully.")
        return cls._instance

qg_pipeline = QuestionGenerationModel.get_pipeline()

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[^\w\s\.\,\?\!\-\(\)\:\;\"\']', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_keywords_and_entities(sentence_doc) -> List[str]:
    candidates = []
    for ent in sentence_doc.ents:
        if 1 <= len(ent.text.split()) <= 3:
            candidates.append(ent.text.strip())
            
    for chunk in sentence_doc.noun_chunks:
        cleaned_chunk = re.sub(r'^(the|a|an)\s+', '', chunk.text, flags=re.IGNORECASE).strip()
        if 1 <= len(cleaned_chunk.split()) <= 3 and cleaned_chunk not in candidates:
            candidates.append(cleaned_chunk)
            
    if not candidates:
        for token in sentence_doc:
            if token.pos_ in ["NOUN", "PROPN"] and len(token.text) > 3:
                candidates.append(token.text.strip())
                
    unique_candidates = []
    for c in candidates:
        if c not in unique_candidates:
            unique_candidates.append(c)
    return unique_candidates

def generate_distractors_wordnet(correct_answer: str, fallback_pool: List[str]) -> List[str]:
    distractors = []
    formatted_word = correct_answer.lower().replace(" ", "_")
    synsets = wordnet.synsets(formatted_word, pos=wordnet.NOUN)
    
    if synsets:
        for synset in synsets:
            for hypernym in synset.hypernyms():
                for hyponym in hypernym.hyponyms():
                    name = hyponym.lemmas()[0].name().replace("_", " ").title()
                    if name.lower() != correct_answer.lower() and name not in distractors:
                        distractors.append(name)
                        
            for lemma in synset.lemmas():
                name = lemma.name().replace("_", " ").title()
                if name.lower() != correct_answer.lower() and name not in distractors:
                    distractors.append(name)

    for alternate in fallback_pool:
        clean_alt = alternate.strip().title()
        if clean_alt.lower() != correct_answer.lower() and clean_alt not in distractors:
            distractors.append(clean_alt)

    base_fallbacks = ["Alternative Concept A", "Alternative Concept B", "Alternative Concept C"]
    idx = 0
    while len(distractors) < 3:
        fallback_option = f"{correct_answer} Variant" if idx >= len(base_fallbacks) else base_fallbacks[idx]
        if fallback_option not in distractors:
            distractors.append(fallback_option)
        idx += 1

    return distractors[:3]

def generate_mcq_pipeline(raw_text: str, num_questions: int) -> List[Dict[str, Any]]:
    cleaned_text = clean_text(raw_text)
    doc = nlp(cleaned_text)
    sentences = [sent.text.strip() for sent in doc.sents if len(sent.text.strip()) > 15]
    
    questions_built = []
    generator = QuestionGenerationModel.get_pipeline()
    
    for sentence in sentences:
        if len(questions_built) >= num_questions:
            break
            
        sent_doc = nlp(sentence)
        answer_candidates = extract_keywords_and_entities(sent_doc)
        if not answer_candidates:
            continue
            
        target_answer = answer_candidates[0].strip().title()
        t5_input_prompt = f"generate question: context: {sentence} answer: {target_answer}"
        
        try:
            generation_output = generator(
                t5_input_prompt,
                max_length=64,
                num_beams=4,
                early_stopping=True
            )
            generated_question_text = generation_output[0]["generated_text"].strip()
            if len(generated_question_text) < 10:
                continue
        except Exception as model_err:
            print(f"WARNING: Model inference step bypassed: {str(model_err)}")
            continue
            
        other_extracted_candidates = answer_candidates[1:]
        distractors = generate_distractors_wordnet(target_answer, other_extracted_candidates)
        
        options_pool = [target_answer] + distractors
        random.shuffle(options_pool)
        
        questions_built.append({
            "question_text": generated_question_text,
            "options": options_pool,
            "answer_key": target_answer
        })
        
    return questions_built