from .health import insight_health_bp
from .project import insight_project_bp
from . import version_profiles as _version_profiles
from . import output_analysis as _output_analysis
from . import history as _history

__all__ = ["insight_health_bp", "insight_project_bp"]
