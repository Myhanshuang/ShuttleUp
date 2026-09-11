import { describe, expect, it } from 'vitest'
import { money } from '../src/format'

describe('money', () => {
  it('formats integer cents without float arithmetic', () => {
    expect(money(4200)).toBe('¥42.00')
    expect(money(1)).toBe('¥0.01')
    expect(money(null)).toBe('价格待确认')
  })
})

