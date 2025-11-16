# Rich CLI Features

This document describes the Rich library features implemented in n8n-snap's CLI output.

## Overview

The CLI now uses Rich's `Live` display to update content in place rather than scrolling output continuously. This provides a much cleaner and more professional user experience.

## Features Implemented

### 1. Live Display (In-Place Updates)
- **What it does**: Updates the same area of the terminal instead of scrolling
- **Where**: Both single-worker and multi-worker modes
- **Refresh rate**: 4 times per second for smooth updates

### 2. Single Worker Mode

**Current Status Panel** shows:
- Current workflow being rendered with status emoji (⏳ rendering, ✓ success, ✗ failed)
- Elapsed time for current workflow (updates in real-time)
- Success/Failed/Remaining counters
- Memory and CPU usage
- ETA (Estimated Time to Arrival) for job completion

**Progress Bar** shows:
- Spinner animation
- Current operation description
- Visual progress bar
- Percentage complete
- Estimated time remaining

### 3. Multi-Worker Mode

**Worker Status Panel** shows:
- Status of each worker (Idle, Rendering with workflow name, Completed)
- Elapsed time per workflow being rendered
- Clean visualization of parallel operations

**Statistics Panel** shows:
- Success/Failed/Remaining counters
- Memory and CPU usage
- ETA for job completion
- Throughput (workflows per minute)

**Progress Bar**: Same as single worker mode

### 4. Final Summary Panel

Shows a clean summary with:
- ✓ Success count
- ✗ Failed count
- ⟳ Replaced count (if any)
- ⏱ Total time taken
- Throughput (multi-worker only)
- Output location
- Border color: Green if all succeeded, Yellow if any failed

## Rich Components Used

```python
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
```

### Key Patterns

1. **Live Display Setup**:
```python
with Live(make_display(), console=console, refresh_per_second=4) as live:
    # Your rendering loop
    live.update(make_display())  # Update when needed
```

2. **Grouped Components**:
```python
def make_display():
    return Group(
        make_status_panel(),
        make_stats_panel(),
        progress
    )
```

3. **Dynamic Panels**:
```python
def make_status_panel():
    """Function that generates panel content dynamically"""
    return Panel(
        content_text,
        title="Status",
        border_style="cyan"
    )
```

4. **Progress with Manual Refresh**:
```python
progress = Progress(
    # ... columns ...
    auto_refresh=False,  # Disable auto-refresh, let Live handle it
)
```

## Resource Monitoring

Uses `psutil` to track:
- Memory usage (RSS in MB)
- CPU percentage

```python
process = psutil.Process()
memory_mb = process.memory_info().rss / (1024 * 1024)
cpu_percent = process.cpu_percent()
```

## Time Tracking

- **Start time**: Captured at beginning of processing
- **Current workflow time**: Tracked per workflow/worker
- **ETA calculation**: Based on average time per workflow
- **Total elapsed**: Shown in final summary

## Color Coding

- **Green**: Success states, positive metrics
- **Red**: Failures, errors
- **Yellow**: In-progress, warnings
- **Cyan**: Informational text
- **Dim**: Secondary information (timestamps, file paths)

## Benefits

1. **Cleaner output**: No scrolling, content updates in place
2. **Real-time feedback**: See progress as it happens
3. **Resource awareness**: Monitor memory/CPU usage
4. **Better planning**: ETA helps estimate completion time
5. **Professional appearance**: Polished, modern CLI experience

## Example Output

```
┌─ Worker Status (4 workers) ────────────────────────────┐
│  Worker 0: ⏳ My Complex Workflow.json (12.3s)         │
│  Worker 1: ✓ Another Workflow.json                     │
│  Worker 2: ⏳ Big Workflow.json (8.1s)                  │
│  Worker 3: Idle                                         │
└─────────────────────────────────────────────────────────┘
┌─ Statistics ────────────────────────────────────────────┐
│  ✓ Success: 45  ✗ Failed: 2  Remaining: 23             │
│  Memory: 834.2 MB  CPU: 45.3%  ETA: 2m 15s              │
└─────────────────────────────────────────────────────────┘
⠋ Rendering workflows... ━━━━━━━━━━━╸━━━━━━━━━ 68% 0:01:30
```

## Future Enhancement Ideas

- **Scrollable log window** for detailed error messages
- **Interactive mode** to pause/resume workers
- **Chart visualization** for throughput over time
- **Color themes** (dark/light mode support)
- **Export display** to HTML for documentation
