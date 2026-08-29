"""Pydantic schemas for Phase 11 — Patch & Test Generation."""
from typing import List, Dict, Optional, Any, Union
from pydantic import BaseModel, Field
from datetime import datetime


class PatchChange(BaseModel):
    file: str
    action: str = Field(..., description="modify | create | delete")
    description: Optional[str] = None
    old_code: Optional[str] = ""
    new_code: str = ""
    line_start: Optional[int] = None
    line_end: Optional[int] = None


class TestToAdd(BaseModel):
    file: str
    test_type: str = "regression"  # regression, unit, integration
    framework: str = "pytest"  # pytest, jest, vitest, gotest, cargo, junit
    test_name: str
    test_code: str
    target_symbol: Optional[str] = None


class PatchGenerateRequest(BaseModel):
    incident_id: Optional[str] = None
    work_item_id: Optional[str] = None
    repository_id: Optional[str] = None
    scope_files: Optional[List[str]] = None
    instructions: Optional[str] = None
    base_commit_sha: Optional[str] = None
    target_branch: Optional[str] = "main"


class PatchEditRequest(BaseModel):
    changes: List[PatchChange]
    tests_to_add: Optional[List[TestToAdd]] = None
    tests_to_run: Optional[List[List[str]]] = None
    rollback_plan: Optional[str] = None


class PatchValidateRequest(BaseModel):
    repository_id: Optional[str] = None
    base_commit_sha: Optional[str] = None
    changes: List[PatchChange]
    scope_files: Optional[List[str]] = None


class PatchSafetyResultOut(BaseModel):
    is_safe: bool
    rejection_reason: Optional[str] = None
    scope_valid: bool = True
    replacements_valid: bool = True
    secrets_clean: bool = True
    ast_valid: bool = True
    bloat_valid: bool = True
    snapshot_hash: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class GeneratedTestOut(BaseModel):
    id: str
    file_path: str
    test_type: str
    framework: str
    test_name: str
    test_code: str
    target_symbol: Optional[str] = None
    pre_patch_result: Optional[str] = None
    post_patch_result: Optional[str] = None
    created_at: Optional[str] = None


class PatchVersionOut(BaseModel):
    id: str
    version_number: int
    editor_user_id: Optional[str] = None
    patch_data: Dict[str, Any]
    diff_content: Optional[str] = None
    previous_snapshot_hash: Optional[str] = None
    new_snapshot_hash: str
    revalidation_status: str
    revalidation_details: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None


class ProposedFixDetailOut(BaseModel):
    id: str
    organization_id: Optional[str] = None
    incident_id: Optional[str] = None
    work_item_id: Optional[str] = None
    repository_id: Optional[str] = None
    repository: Optional[str] = None
    base_commit_sha: Optional[str] = None
    target_branch: Optional[str] = "main"
    title: str
    description: str
    fix_type: Optional[str] = None
    status: str
    diff: Optional[str] = None
    patch: Optional[Dict[str, Any]] = None
    scope_files: Optional[List[str]] = None
    rollback_plan: Optional[str] = None
    regression_test_status: str
    is_rejected: bool
    rejection_reason: Optional[str] = None
    snapshot_hash: Optional[str] = None
    version: int
    tests_to_add: Optional[List[Dict[str, Any]]] = None
    tests_to_run: Optional[List[List[str]]] = None
    generated_tests: List[GeneratedTestOut] = []
    versions: List[PatchVersionOut] = []
    branch_name: Optional[str] = None
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    generated_at: Optional[str] = None


class ValidationCheckRunOut(BaseModel):
    id: str
    check_type: str
    name: str
    command: List[str]
    status: str
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    duration_ms: float = 0.0
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ValidationReportOut(BaseModel):
    validation_id: str
    fix_id: str
    organization_id: str
    repository_id: Optional[str] = None
    base_commit_sha: str
    verified_base_sha: Optional[str] = None
    workspace_id: str
    status: str
    compilation_status: str
    tests_status: str
    original_failure_reproduced: str
    failure_absent_after_patch: str
    scenario_replay_status: str
    production_outcome: str
    overall_status: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    summary_report: Optional[Dict[str, Any]] = None
    check_runs: List[ValidationCheckRunOut] = []


class ReplayScenarioRequest(BaseModel):
    timeout_sec: Optional[int] = 30

