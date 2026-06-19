import gradio as gr

import intake as intake_mod
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
                    label="📎 Upload property images (optional, multiple allowed)",
                    file_types=["image"],
                    file_count="multiple",
                )

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

        # Update checklist when images are added/removed
        image_upload.change(
            lambda files, fields, desc: intake_mod.render_checklist(fields, bool(files), desc),
            [image_upload, fields_state, description_box],
            fields_display,
        )

        # Update checklist when user edits description directly
        description_box.change(
            lambda desc, fields, files: intake_mod.render_checklist(fields, bool(files), desc),
            [description_box, fields_state, image_upload],
            fields_display,
        )

        def _do_submit(fields, description, image_files):
            result = submission_mod.submit_from_chat(fields, description, image_files)
            return gr.update(value=result, visible=True)

        submit_btn.click(
            _do_submit,
            [fields_state, description_box, image_upload],
            submission_result,
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # Tab 2 — Submissions
    # ═══════════════════════════════════════════════════════════════════════════
    with gr.Tab("📋 Submissions"):
        gr.Markdown(
            "Enter a **Job ID** from a previous submission to check its current status."
        )

        with gr.Row():
            job_id_input = gr.Textbox(
                label="Job ID",
                placeholder="e.g. a1b2c3d4-…",
                scale=4,
            )
            check_btn = gr.Button("Check Status", variant="primary", scale=1)

        status_display = gr.Markdown("*No job ID entered yet.*")

        check_btn.click(submission_mod.check_status_once, job_id_input, status_display)
        job_id_input.submit(submission_mod.check_status_once, job_id_input, status_display)

if __name__ == "__main__":
    app.launch(
        server_name=GRADIO_SERVER_NAME,
        server_port=GRADIO_SERVER_PORT,
        show_error=True,
        theme=gr.themes.Soft(),
    )
