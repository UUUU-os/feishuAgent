type StepListProps = {
  steps: Array<{
    title: string;
    description: string;
    state?: "done" | "active" | "pending" | "danger";
  }>;
};

export function StepList({ steps }: StepListProps) {
  return (
    <ol className="step-list">
      {steps.map((step, index) => (
        <li key={step.title} className={`step-list__item step-list__item--${step.state ?? "pending"}`}>
          <span>{index + 1}</span>
          <div>
            <strong>{step.title}</strong>
            <small>{step.description}</small>
          </div>
        </li>
      ))}
    </ol>
  );
}
