import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Testing Library unmounts after each test on its own only when vitest runs
// with `globals: true`, which this repo does not — tests import `test` and
// `expect` explicitly. Without this, one test's DOM is still mounted during
// the next one and `screen` queries find both.
afterEach(cleanup)
