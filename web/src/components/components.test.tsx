import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Brand } from './Brand';
import { Feedback } from './Feedback';
import { Orb } from '../features/chat/Orb';

describe('shared visual status components', () => {
  it('renders the canonical brand and accessible error feedback', () => {
    render(
      <>
        <Brand />
        <Feedback kind="error">Spojení selhalo</Feedback>
      </>,
    );
    expect(screen.getByText('KájovoDagmar')).toBeVisible();
    expect(screen.getByText('VIRTUÁLNÍ ASISTENTKA')).toBeVisible();
    expect(screen.getByRole('alert')).toHaveTextContent('Spojení selhalo');
  });

  it('renders notices and exposes voice state textually', () => {
    const onActivate = vi.fn();
    const { rerender } = render(<Feedback kind="success">Uloženo</Feedback>);
    expect(screen.getByRole('status')).toHaveTextContent('Uloženo');
    rerender(<Orb state="listening" onActivate={onActivate} />);
    screen.getByRole('button', { name: /Stav asistentky: listening/ }).click();
    expect(onActivate).toHaveBeenCalledOnce();
  });
});
