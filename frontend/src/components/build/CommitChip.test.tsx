import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import CommitChip from './CommitChip'

const SHA = '3f2a9c1d4b5e6f708192a3b4c5d6e7f809a1b2c3'

describe('CommitChip', () => {
  it('shows the short commit and copies the full one', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })

    render(<CommitChip sha={SHA} />)
    const chip = screen.getByRole('button', { name: `Commit ${SHA}, copy` })
    expect(chip).toHaveTextContent('3f2a9c1')
    expect(chip).not.toHaveTextContent(SHA)

    fireEvent.click(chip)
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(SHA))
  })
})
