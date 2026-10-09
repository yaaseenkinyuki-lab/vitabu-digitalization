import streamlit as st
from google import genai
from PIL import Image
import io
import os
import time
import requests
import gc
import re

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import arabic_reshaper
from bidi.algorithm import get_display

try:
    from streamlit_paste_button import paste_image_button
except ImportError:
    paste_image_button = None

# 1. Pakua na kusajili Font ya Amiri kiotomatiki
FONT_PATH = "Amiri-Regular.ttf"
if not os.path.exists(FONT_PATH):
    try:
        font_url = "https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Regular.ttf"
        res = requests.get(font_url)
        with open(FONT_PATH, "wb") as f:
            f.write(res.content)
    except Exception as e:
        st.error(f"Hitilafu katika kupakua Fonti ya Amiri: {e}")

if os.path.exists(FONT_PATH):
    pdfmetrics.registerFont(TTFont('Amiri', FONT_PATH))

# Sanidi reshaper kuhifadhi Shakil/Harakati zote kamilifu
reshaper_config = {
    'delete_harakat': False,
    'support_ligatures': True
}
reshaper = arabic_reshaper.ArabicReshaper(configuration=reshaper_config)

st.set_page_config(page_title="MIMAM Digitization Studio", layout="centered", page_icon="📚")
st.title("📚 MIMAM Digitization & Tafsiri ya Vitabu")

# Sidebar ya Mipangilio
with st.sidebar:
    st.header("⚙️ Mipangilio")
    api_key = st.text_input("Weka Gemini API Key Yako:", type="password")
    st.info("💡 Mfumo huu unafanya kazi 24/7. Weka API Key yako mpya hapa kuanza kuchakata.")

if "clipboard_images" not in st.session_state:
    st.session_state.clipboard_images = []

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📋 Paste Maandishi", 
    "🔗 Paste Image URL", 
    "📸 Kamera Direct", 
    "📁 Upload Picha Nyingi",
    "🖼️ Paste Picha Nyingi (Clipboard)"
])

mode = None
items_to_process = []

with tab1:
    st.subheader("1. Paste Maandishi ya Kiarabu Direct")
    pasted_text = st.text_area("Weka au Paste maandishi ya Kiarabu hapa:", height=180)
    if pasted_text:
        mode = "text"
        items_to_process = [("Maandishi Direct", pasted_text)]

with tab2:
    st.subheader("2. Paste Link / URL ya Picha")
    img_url = st.text_input("Paste URL au Link ya picha hapa:")
    if img_url:
        mode = "url"
        items_to_process = [("Link ya Picha", img_url)]

with tab3:
    st.subheader("3. Piga Picha ya Ukurasa (Kamera)")
    camera_file = st.camera_input("Piga picha moja kwa moja kutoka kwenye kitabu")
    if camera_file:
        mode = "image_single"
        items_to_process = [("Picha ya Kamera", camera_file)]

with tab4:
    st.subheader("4. Upload Picha Nyingi za Kitabu")
    uploaded_files = st.file_uploader("Pakia Picha Nyingi za Kitabu kwa Mara Moja:", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])
    if uploaded_files:
        mode = "multi_images"
        for idx, f in enumerate(uploaded_files, start=1):
            items_to_process.append((f"Ukurasa {idx}", f))

with tab5:
    st.subheader("5. Paste Picha Nyingi Kutoka Clipboard")
    st.caption("Bofya kitufe cha Blue hapa chini kupaste picha nyingi moja baada ya nyingine:")
    
    if paste_image_button:
        paste_result = paste_image_button(
            label="📋 CLICK HERE TO PASTE IMAGE FROM CLIPBOARD",
            background_color="#2196F3",
            text_color="#FFFFFF",
            errors="ignore"
        )
        if paste_result.image_data is not None:
            img_obj = paste_result.image_data.convert("RGB")
            st.session_state.clipboard_images.append(img_obj)
            st.success(f"✅ Picha imeongezwa! Jumla ya picha zilizopastiwa: {len(st.session_state.clipboard_images)}")

    if st.session_state.clipboard_images:
        st.write("---")
        st.write(f"📸 **Orodha ya Picha Ulizopaste ({len(st.session_state.clipboard_images)}):**")
        cols = st.columns(min(len(st.session_state.clipboard_images), 4))
        for i, img in enumerate(st.session_state.clipboard_images):
            cols[i % 4].image(img, caption=f"Picha {i+1}", use_column_width=True)
            
        if st.button("🗑️ Futa Picha Zote Ulizopaste"):
            st.session_state.clipboard_images = []
            st.rerun()

        mode = "multi_images"
        for idx, img in enumerate(st.session_state.clipboard_images, start=1):
            items_to_process.append((f"Picha Iliyopastiwa {idx}", img))

PROMPT_INSTRUCTION = """
Wewe ni mtaalamu wa lugha ya Kiarabu na masomo ya Kiislamu.
Soma maandishi/picha hii ya Kiarabu na uitengeneze kwa muundo safi wa kitabu halisi (Pure Academic Book Format):

KANUNI KUU ZA MUUNDO (ZINGATIA KWA UMAKINI):
1. Kila neno na kifungu cha Kiarabu LAZIMA kiwe na Shakil/Harakati zote kamilifu (Fatha, Kasra, Dhamma, Sukun, Shadda na Tanween) kwa usahihi wa kisarufi (Tashkeel Taam).
2. Weka kifungu cha Kiarabu, kisha mara moja weka Tafsiri yake ya Kiswahili fasaha cha kitaaluma hapo chini.
3. MPANGILIO WA MISTARI: Andika sentensi za Kiarabu kutoka Juu kwenda Chini kwa mfululizo wa kawaida. Usibadili mwelekeo wa mistari.
4. KANUNI YA PURE FORMAT:
   - USIANDIKE maneno kama "Kifungu 1", "Kifungu 2", "Sura 1", n.k.
   - USIWEKE kabisa lebo za [KIARABU], [TAFSIRI], au [KISWAHILI].
   - USIWEKE kabisa alama za markdown kama ***, ---, ###, au **.
   - USIWEKE kabisa transliteration / romanization ya herufi za Latin.
   - Leta maandishi tu: Kiarabu chenye shakil, kikifuatiwa na Kiswahili moja kwa moja.
"""

MODEL_NAME = "gemini-3.8-flash"

def compress_image(img_raw):
    img = img_raw.convert("RGB")
    img.thumbnail((1280, 1280))
    return img

def clean_text_pure(text):
    cleaned = re.sub(r'\*+\*+', '', text)
    cleaned = re.sub(r'---+', '', cleaned)
    cleaned = re.sub(r'#+', '', cleaned)
    cleaned = re.sub(r'\[KIARABU\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\[TAFSIRI\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\[KISWAHILI\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'Kifungu\s*\d+:?', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

def process_arabic_paragraph(text):
    lines = text.split('\n')
    processed_lines = []
    for line in lines:
        line_clean = line.strip()
        if line_clean:
            reshaped = reshaper.reshape(line_clean)
            bidi_line = get_display(reshaped)
            processed_lines.append(bidi_line)
    return "<br/>".join(processed_lines)

def call_gemini_pure(client, contents_payload):
    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents_payload
            )
            if response and response.text:
                return clean_text_pure(response.text)
        except Exception as e:
            if attempt == 3:
                raise e
            time.sleep((attempt + 1) * 3)

if api_key and items_to_process:
    st.divider()
    if st.button("🚀 Anza Kuchakata Zote & Kutengeneza PDF"):
        client = genai.Client(api_key=api_key)
        matokeo_yote = []
        
        total_items = len(items_to_process)
        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, (label, item_data) in enumerate(items_to_process, start=1):
            status_text.text(f"⏳ Inachakata {label} ({idx}/{total_items})...")
            
            try:
                if mode == "text":
                    prompt = f"{PROMPT_INSTRUCTION}\n\nMaandishi:\n{item_data}"
                    res_text = call_gemini_pure(client, [prompt])
                elif mode == "url":
                    res = requests.get(item_data)
                    img_obj = Image.open(io.BytesIO(res.content))
                    compressed_img = compress_image(img_obj)
                    res_text = call_gemini_pure(client, [compressed_img, PROMPT_INSTRUCTION])
                else:
                    if isinstance(item_data, str):
                        img_obj = Image.open(item_data)
                    elif hasattr(item_data, 'read'):
                        img_obj = Image.open(item_data)
                    else:
                        img_obj = item_data
                        
                    compressed_img = compress_image(img_obj)
                    prompt = f"{label}:\n{PROMPT_INSTRUCTION}"
                    res_text = call_gemini_pure(client, [compressed_img, prompt])

                matokeo_yote.append((idx, res_text))
                st.markdown(f"### {label}")
                st.text_area(f"Matokeo {idx}:", res_text, height=200)

            except Exception as e:
                st.error(f"Imeshindwa kuchakata {label}: {e}")
            
            gc.collect()
            progress_bar.progress(idx / total_items)

        status_text.text("✅ Mchakato umekamilika! Inaandaa Kitabu cha PDF...")

        if matokeo_yote:
            pdf_buffer = io.BytesIO()
            doc = SimpleDocTemplate(
                pdf_buffer, 
                pagesize=letter,
                rightMargin=45, leftMargin=45, topMargin=45, bottomMargin=45
            )
            story = []
            styles = getSampleStyleSheet()
            
            arabic_style = ParagraphStyle(
                'ArabicStylePure',
                parent=styles['Normal'],
                fontName='Amiri',
                fontSize=16,
                leading=28,
                alignment=2,
                wordWrap='RTL'
            )
            
            swahili_style = ParagraphStyle(
                'SwahiliStylePure',
                parent=styles['Normal'],
                fontSize=12,
                leading=18,
                alignment=0
            )

            for namba, teksti in matokeo_yote:
                blocks = teksti.split('\n\n')
                for block in blocks:
                    cleaned_block = clean_text_pure(block)
                    if not cleaned_block:
                        continue
                    if any('\u0600' <= c <= '\u06FF' for c in cleaned_block):
                        formatted_arabic = process_arabic_paragraph(cleaned_block)
                        story.append(Paragraph(formatted_arabic, arabic_style))
                    else:
                        story.append(Paragraph(cleaned_block.replace('\n', '<br/>'), swahili_style))
                    story.append(Spacer(1, 6))

                story.append(Spacer(1, 14))

            doc.build(story)
            pdf_data = pdf_buffer.getvalue()
            
            st.download_button(
                label="📥 Pakua Kitabu Chako Cha PDF (Pure Layout)",
                data=pdf_data,
                file_name="Kitabu_Tafsiri_MIMAM_Pure.pdf",
                mime="application/pdf"
            )
