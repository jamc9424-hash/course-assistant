"""Course Assistant — a grounded, multimodal course assistant.

Public entry points:
  * ``python -m course_assistant.app``  -> launch the Gradio interface
  * ``python -m course_assistant.eval`` -> run the evaluation question set
  * ``course_assistant.CourseAssistant`` for programmatic use.
"""

from .store import CourseAssistant, DocumentError

__all__ = ["CourseAssistant", "DocumentError"]
__version__ = "0.1.0"
