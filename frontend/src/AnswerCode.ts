export function answerCode(format?: string) {
  const pool = format === 'six_printable_ascii'
  const six = pool || format === 'six_ascii_alphanumeric'
  return { length: six ? 6 : 4, pattern: pool ? '[\u0021-\u007E]{6}' : six ? '[A-Za-z0-9]{6}' : '[0-9]{4}', inputMode: six ? 'text' as const : 'numeric' as const, label: six ? 'Six-character answer code' : 'Four-digit answer' }
}
