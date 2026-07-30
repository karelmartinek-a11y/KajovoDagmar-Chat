export function Feedback({ kind, children }: { kind: 'error' | 'success'; children: string }) {
  return (
    <div className={kind} role={kind === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  );
}
