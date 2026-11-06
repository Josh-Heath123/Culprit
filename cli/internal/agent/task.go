package agent

import (
	"fmt"
	"regexp"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The two things a task can be (Phase 33, "What a task can be").
const (
	TaskProbe    = "probe"
	TaskDiagnose = "diagnose"
)

// Task is one unit of work. In part 1 it arrives as a JSON file in a
// local directory; in part 2, over the transport. Either way it is a
// request, and the agent decides whether it may be done.
type Task struct {
	ID          string `json:"id"`
	Environment string `json:"environment"`
	Kind        string `json:"kind"`
	// Probe is set for kind "probe": one named probe, on one target.
	Probe *ProbeTask `json:"probe,omitempty"`
	// Diagnose is set for kind "diagnose": walk from a symptom.
	Diagnose *DiagnoseTask `json:"diagnose,omitempty"`
	// Allowance, when present, is the capabilities whoever sent the task
	// permits it to use. It can only narrow the agent's own grants; a
	// name the agent does not hold is ignored and recorded. Absent means
	// the agent's grants, unnarrowed.
	Allowance []string `json:"allowance,omitempty"`
}

// ProbeTask names a probe and its target.
type ProbeTask struct {
	ProbeID string         `json:"probe_id"`
	Target  string         `json:"target"`
	Inputs  map[string]any `json:"inputs,omitempty"`
}

// DiagnoseTask is `culprit diagnose` as a task.
type DiagnoseTask struct {
	Symptom string `json:"symptom"`
	// From is the component this agent runs inside, if any.
	From string `json:"from,omitempty"`
}

var taskID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)

// Validate checks a task's shape. A task that does not validate is
// never run; its result says why.
func (t Task) Validate() error {
	if !taskID.MatchString(t.ID) {
		return fmt.Errorf("task id must be 1-128 letters, digits, '.', '_' or '-'")
	}
	if t.Environment == "" {
		return fmt.Errorf("task %s names no environment", t.ID)
	}
	switch t.Kind {
	case TaskProbe:
		if t.Probe == nil || t.Probe.ProbeID == "" || t.Probe.Target == "" || t.Diagnose != nil {
			return fmt.Errorf("task %s: a probe task needs probe.probe_id and probe.target, and nothing else", t.ID)
		}
		if _, _, err := model.ParseSubject(t.Probe.Target); err != nil {
			return fmt.Errorf("task %s: the target is not a subject URI", t.ID)
		}
	case TaskDiagnose:
		if t.Diagnose == nil || t.Diagnose.Symptom == "" || t.Probe != nil {
			return fmt.Errorf("task %s: a diagnose task needs diagnose.symptom, and nothing else", t.ID)
		}
	default:
		return fmt.Errorf("task %s: kind must be %q or %q", t.ID, TaskProbe, TaskDiagnose)
	}
	return nil
}

// Outcome is how a task ended.
const (
	OutcomeCompleted = "completed"
	OutcomeRefused   = "refused"
	OutcomeError     = "error"
)

// Result is what the agent hands back for a task. It is written only
// after every audit entry for the task is on disk.
type Result struct {
	TaskID      string    `json:"task_id"`
	AgentID     string    `json:"agent_id,omitempty"`
	Environment string    `json:"environment,omitempty"`
	Kind        string    `json:"kind,omitempty"`
	Outcome     string    `json:"outcome"`
	Reason      string    `json:"reason,omitempty"`
	StartedAt   time.Time `json:"started_at"`
	FinishedAt  time.Time `json:"finished_at"`
	// GrantsHeld is what the task ran under: the configuration's grants
	// for its environment, narrowed by the allowance.
	GrantsHeld []string `json:"grants_held"`
	// AllowanceIgnored is any capability the allowance named that the
	// agent does not hold — asked for, not given.
	AllowanceIgnored []string `json:"allowance_ignored,omitempty"`

	Readings      []model.Reading      `json:"readings,omitempty"`
	Investigation *model.Investigation `json:"investigation,omitempty"`
}
