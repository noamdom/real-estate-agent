import gradio as gr

import intake as intake_mod
import properties as properties_mod
import submission as submission_mod
from config import GRADIO_SERVER_NAME, GRADIO_SERVER_PORT

_GREETING = (
    "Hello! I'm your property intake assistant. "
    "Please describe the property you'd like to list — "
    "type, location, condition, intent (sell or rent), and any key features."
)

with gr.Blocks(title="AI Property Triage System") as app:
    gr.Markdown("# 🏠 AI Property Triage System")

    # ── Shared state ──────────────────────────────────────────────────────────
    fields_state = gr.State({})
    last_llm_desc_state = gr.State("")

    # ═══════════════════════════════════════════════════════════════════════════
    # Tab 1 — Intake Assistant
    # ═══════════════════════════════════════════════════════════════════════════
    with gr.Tab("💬 Intake Assistant"):
        with gr.Row():

            # ── Left column: chat ─────────────────────────────────────────────
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    value=[{"role": "assistant", "content": _GREETING}],
                    height=420,
                    show_label=False,
                )

                with gr.Row():
                    msg_input = gr.Textbox(
                        placeholder="Describe your property or answer the assistant's questions…",
                        show_label=False,
                        scale=5,
                        autofocus=True,
                    )
                    send_btn = gr.Button("Send", variant="secondary", scale=1)

                image_upload = gr.File(
                    label="📎 Upload property images — max 5 (optional)",
                    file_types=["image"],
                    file_count="multiple",
                )
                image_limit_warning = gr.Markdown(visible=False)

                gr.Markdown("---")
                submit_btn = gr.Button("📤 Submit Listing", variant="primary", size="lg")
                submission_result = gr.Markdown(visible=False)

            # ── Right column: checklist + description draft ───────────────────
            with gr.Column(scale=1, min_width=260):
                fields_display = gr.Markdown(
                    intake_mod.render_checklist({})
                )

                gr.Markdown("---")
                gr.Markdown("#### 📝 Draft Description")
                description_box = gr.Textbox(
                    label="",
                    lines=6,
                    placeholder="Auto-generated from your conversation — edit freely before submitting.",
                    interactive=True,
                    show_label=False,
                )
                gr.Markdown(
                    "<small>*Generated automatically. Your edits are preserved.*</small>",
                    visible=True,
                )

        # ── Event wiring ─────────────────────────────────────────────────────
        respond_inputs = [
            msg_input, chatbot, image_upload,
            fields_state, description_box, last_llm_desc_state,
        ]
        respond_outputs = [
            chatbot, fields_display, fields_state,
            msg_input, description_box, last_llm_desc_state,
        ]

        send_btn.click(intake_mod.intake_respond, respond_inputs, respond_outputs)
        msg_input.submit(intake_mod.intake_respond, respond_inputs, respond_outputs)

        MAX_IMAGES = 5

        def _on_images_change(files, fields, desc):
            too_many = isinstance(files, list) and len(files) > MAX_IMAGES
            warning = gr.update(
                value=f"⚠️ Please remove images — max {MAX_IMAGES} allowed.",
                visible=too_many,
            )
            checklist = intake_mod.render_checklist(fields, bool(files), desc)
            btn = gr.update(interactive=not too_many)
            return checklist, warning, btn

        # Update checklist when images are added/removed
        image_upload.change(
            _on_images_change,
            [image_upload, fields_state, description_box],
            [fields_display, image_limit_warning, submit_btn],
        )

        # Update checklist when user edits description directly
        description_box.change(
            lambda desc, fields, files: intake_mod.render_checklist(fields, bool(files), desc),
            [description_box, fields_state, image_upload],
            fields_display,
        )

        def _do_submit(fields, description, image_files):
            if isinstance(image_files, list) and len(image_files) > MAX_IMAGES:
                image_files = image_files[:MAX_IMAGES]
            result = submission_mod.submit_from_chat(fields, description, image_files)
            return gr.update(value=result, visible=True)

        submit_btn.click(
            _do_submit,
            [fields_state, description_box, image_upload],
            submission_result,
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # Tab 2 — Properties
    # ═══════════════════════════════════════════════════════════════════════════
    with gr.Tab("🏠 Properties"):
        with gr.Row():

            # ── Left column: active filters + results ─────────────────────────
            with gr.Column(scale=3):
                with gr.Row():
                    filter_location  = gr.Textbox(label="Location", scale=2)
                    filter_type      = gr.Dropdown(
                        ["", "apartment", "villa", "commercial", "land"],
                        label="Type",
                        scale=1,
                    )
                    filter_min_rooms = gr.Number(label="Min rooms", scale=1, minimum=0)
                    filter_max_price = gr.Number(label="Max price (NIS)", scale=1, minimum=0)
                    refresh_btn      = gr.Button("🔄 Refresh", scale=1)

                properties_display = gr.Markdown(
                    "*Use the chat or click Refresh to load listings.*",
                    sanitize_html=False,
                )

            # ── Right column: filter chatbot ──────────────────────────────────
            with gr.Column(scale=1, min_width=300):
                gr.Markdown("#### 🤖 Filter Assistant")
                filter_chatbot = gr.Chatbot(
                    value=[{
                        "role": "assistant",
                        "content": (
                            "Hi! Tell me what you're looking for — e.g. "
                            "*'3 rooms in Tel Aviv'* or "
                            "*'commercial property under 2M NIS'*."
                        ),
                    }],
                    height=380,
                    show_label=False,
                    buttons=[],
                )
                with gr.Row():
                    filter_msg = gr.Textbox(
                        placeholder="Describe what you're looking for…",
                        show_label=False,
                        scale=5,
                        autofocus=False,
                    )
                    filter_send = gr.Button("Search", variant="primary", scale=1)
                gr.ClearButton(
                    [filter_chatbot],
                    value="🗑 Clear chat",
                    size="sm",
                )

        # ── Shared interactive controls (needed in both handlers) ─────────────
        _controls = [filter_location, filter_type, filter_min_rooms, filter_max_price,
                     filter_send, refresh_btn]

        # ── Chat-driven filtering ─────────────────────────────────────────────
        def _chat_filter(message, history, location, ptype, rooms, price):
            interim = list(history) + [{"role": "user", "content": message}]
            yield (
                interim, "",
                gr.update(interactive=False), gr.update(interactive=False),
                gr.update(interactive=False), gr.update(interactive=False),
                gr.update(interactive=False),
                gr.update(interactive=False, value="↻ Loading…"),
                gr.update(),
            )
            new_hist, new_loc, new_type, new_rooms, new_price, rendered = \
                properties_mod.chat_filter(message, history)
            yield (
                new_hist, "",
                gr.update(value=new_loc,          interactive=True),
                gr.update(value=new_type or "",   interactive=True),
                gr.update(value=new_rooms,        interactive=True),
                gr.update(value=new_price,        interactive=True),
                gr.update(interactive=True),
                gr.update(interactive=True, value="🔄 Refresh"),
                rendered,
            )

        _chat_inputs  = [filter_msg, filter_chatbot,
                         filter_location, filter_type, filter_min_rooms, filter_max_price]
        _chat_outputs = [filter_chatbot, filter_msg,
                         filter_location, filter_type, filter_min_rooms, filter_max_price,
                         filter_send, refresh_btn, properties_display]

        filter_send.click(
            _chat_filter, _chat_inputs, _chat_outputs, show_progress="hidden",
        )
        filter_msg.submit(
            _chat_filter, _chat_inputs, _chat_outputs, show_progress="hidden",
        )

        # ── Manual refresh ────────────────────────────────────────────────────
        def _load(location, ptype, rooms, price):
            yield (
                gr.update(interactive=False),
                gr.update(interactive=False, value="↻ Loading…"),
                gr.update(interactive=False), gr.update(interactive=False),
                gr.update(interactive=False), gr.update(interactive=False),
                gr.update(),
            )
            rows = properties_mod.fetch_properties(
                location=location or "",
                property_type=ptype or "",
                min_rooms=rooms or None,
                max_price=price or None,
            )
            rendered = properties_mod.render_properties(rows)
            yield (
                gr.update(interactive=True),
                gr.update(interactive=True, value="🔄 Refresh"),
                gr.update(interactive=True), gr.update(interactive=True),
                gr.update(interactive=True), gr.update(interactive=True),
                rendered,
            )

        _load_outputs = [filter_send, refresh_btn,
                         filter_location, filter_type, filter_min_rooms, filter_max_price,
                         properties_display]

        refresh_btn.click(
            _load,
            [filter_location, filter_type, filter_min_rooms, filter_max_price],
            _load_outputs,
            show_progress="hidden",
        )

if __name__ == "__main__":
    app.launch(
        server_name=GRADIO_SERVER_NAME,
        server_port=GRADIO_SERVER_PORT,
        show_error=True,
        theme=gr.themes.Soft(),
    )
