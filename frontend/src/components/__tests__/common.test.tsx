import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { DataTable } from '@/components/common/DataTable'
import { FileDropzone } from '@/components/common/FileDropzone'
import { KpiCard } from '@/components/common/KpiCard'
import { bandFromScore, MatchBar, MatchScoreBadge } from '@/components/common/MatchScore'
import { PageHeader } from '@/components/common/PageHeader'
import { SearchInput } from '@/components/common/SearchInput'
import { SkillChip, SkillChipList } from '@/components/common/SkillChip'
import { EmptyState, ErrorState } from '@/components/common/States'
import { Stepper } from '@/components/common/Stepper'
import { StatusBadge } from '@/components/common/StatusBadge'
import { TextBlock } from '@/components/common/TextBlock'
import { Timeline } from '@/components/common/Timeline'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Combobox, MultiSelect } from '@/components/ui/combobox'
import { Pagination, pageWindow } from '@/components/ui/pagination'
import { SimpleSelect } from '@/components/ui/select'
import { ApiError } from '@/lib/api'

afterEach(() => vi.restoreAllMocks())

describe('StatusBadge', () => {
  it.each([
    ['job', 'PUBLISHED', 'Published'],
    ['job', 'ARCHIVED', 'Archived'],
    ['application', 'SHORTLISTED', 'Shortlisted'],
    ['application', 'REJECTED', 'Rejected'],
    ['resume', 'PROCESSING', 'Processing'],
    ['interview', 'NO_SHOW', 'No-show'],
  ] as const)('%s %s -> "%s" (text, never colour alone)', (kind, status, label) => {
    render(<StatusBadge kind={kind} status={status} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })
  it('degrades gracefully for an unknown status', () => {
    render(<StatusBadge kind="job" status="SOMETHING_NEW" />)
    expect(screen.getByText('Something new')).toBeInTheDocument()
  })
})

describe('match score', () => {
  it.each([
    [0.97, 'STRONG'],
    [0.75, 'STRONG'],
    [0.62, 'GOOD'],
    [0.4, 'PARTIAL'],
    [0.1, 'WEAK'],
  ])('score %s is band %s (same thresholds as the backend)', (score, band) => {
    expect(bandFromScore(score)).toBe(band)
  })
  it('badge shows the percentage and exposes the band to screen readers', () => {
    render(<MatchScoreBadge score={0.824} />)
    expect(screen.getByText('82%')).toBeInTheDocument()
    expect(screen.getByText('Strong match')).toHaveClass('sr-only')
  })
  it('badge renders nothing without a score', () => {
    const { container } = render(<MatchScoreBadge score={null} />)
    expect(container).toBeEmptyDOMElement()
  })
  it('bar is an accessible meter', () => {
    render(<MatchBar percent={62} band="GOOD" />)
    const meter = screen.getByRole('meter', { name: 'Match score' })
    expect(meter).toHaveAttribute('aria-valuenow', '62')
    expect(meter).toHaveAttribute('aria-valuetext', '62% — Good match')
  })
})

describe('Pagination', () => {
  it('builds windows with ellipses', () => {
    expect(pageWindow(1, 1)).toEqual([1])
    expect(pageWindow(1, 5)).toEqual([1, 2, '…', 5])
    expect(pageWindow(10, 20)).toEqual([1, '…', 9, 10, 11, '…', 20])
    expect(pageWindow(20, 20)).toEqual([1, '…', 19, 20])
  })
  it('announces the range, marks the current page and calls back', async () => {
    const onChange = vi.fn()
    render(<Pagination page={2} pages={4} total={35} pageSize={10} onPageChange={onChange} label="jobs" />)
    expect(screen.getByText(/11–20/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Page 2' })).toHaveAttribute('aria-current', 'page')
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }))
    expect(onChange).toHaveBeenCalledWith(3)
    await userEvent.click(screen.getByRole('button', { name: 'Previous page' }))
    expect(onChange).toHaveBeenCalledWith(1)
  })
  it('disables the edges', () => {
    render(<Pagination page={1} pages={3} total={30} pageSize={10} onPageChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()
  })
})

describe('Field', () => {
  it('wires label, hint and error to the control for assistive tech', () => {
    render(
      <Field label="Title" hint="Be specific" error="Required" required>
        <Input />
      </Field>,
    )
    const input = screen.getByLabelText(/Title/)
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAttribute('aria-required', 'true')
    expect(input.getAttribute('aria-describedby')).toContain('-error')
    expect(screen.getByRole('alert')).toHaveTextContent('Required')
    expect(screen.queryByText('Be specific')).not.toBeInTheDocument() // the error replaces the hint
  })
  it('shows the hint when there is no error', () => {
    render(
      <Field label="Title" hint="Be specific">
        <Input />
      </Field>,
    )
    expect(screen.getByLabelText('Title')).toHaveAccessibleDescription('Be specific')
  })
})

describe('States', () => {
  it('EmptyState shows a next action', () => {
    render(<EmptyState title="Nothing yet" description="Add one" action={<button>Add</button>} />)
    expect(screen.getByRole('heading', { name: 'Nothing yet' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument()
  })
  it('ErrorState explains the failure, shows the reference and retries', async () => {
    const retry = vi.fn()
    render(<ErrorState error={new ApiError(500, 'INTERNAL_ERROR', 'x', null, 'req-42')} onRetry={retry} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Service unavailable')
    expect(screen.getByText('Reference: req-42')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /try again/i }))
    expect(retry).toHaveBeenCalled()
  })
  it.each([
    [new ApiError(0, 'NETWORK_ERROR', 'x'), 'Cannot reach the server'],
    [new ApiError(403, 'FORBIDDEN', 'x'), 'Access denied'],
    [new ApiError(404, 'NOT_FOUND', 'Gone'), 'Not found'],
    [new Error('weird'), 'Something went wrong'],
  ])('ErrorState maps %s', (error, title) => {
    render(<ErrorState error={error} />)
    expect(screen.getByRole('heading', { name: title })).toBeInTheDocument()
  })
})

describe('DataTable', () => {
  type Row = { id: string; name: string }
  const columns = [{ key: 'name', header: 'Name', cell: (r: Row) => r.name, sortKey: 'name' }]
  const rows: Row[] = [
    { id: '1', name: 'Alpha' },
    { id: '2', name: 'Beta' },
  ]

  it('renders a semantic table with sortable headers (aria-sort)', async () => {
    const onSort = vi.fn()
    render(
      <DataTable
        caption="People"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        sortKey="name"
        sortDirection="desc"
        onSortChange={onSort}
      />,
    )
    expect(screen.getByRole('table', { name: 'People' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /name/i })).toHaveAttribute('aria-sort', 'descending')
    await userEvent.click(screen.getByRole('button', { name: /name/i }))
    expect(onSort).toHaveBeenCalledWith('name')
  })

  it('has loading, error and empty states', () => {
    const { rerender } = render(
      <DataTable caption="x" columns={columns} rows={undefined} rowKey={(r) => r.id} loading />,
    )
    expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
    rerender(
      <DataTable
        caption="x"
        columns={columns}
        rows={undefined}
        rowKey={(r) => r.id}
        error={new Error('nope')}
      />,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    rerender(
      <DataTable caption="x" columns={columns} rows={[]} rowKey={(r) => r.id} empty={<p>No people</p>} />,
    )
    expect(screen.getByText('No people')).toBeInTheDocument()
  })

  it('switches to cards on small screens (never a page-wide table)', () => {
    window.matchMedia = ((q: string) => ({
      matches: false,
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    })) as unknown as typeof window.matchMedia
    render(
      <DataTable
        caption="People"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        renderCard={(r) => <span>Card {r.name}</span>}
      />,
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getByText('Card Alpha')).toBeInTheDocument()
    // @ts-expect-error cleanup the stub
    delete window.matchMedia
  })

  it('paginates', async () => {
    const onPage = vi.fn()
    render(
      <DataTable
        caption="x"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        page={1}
        pages={3}
        total={25}
        pageSize={10}
        onPageChange={onPage}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }))
    expect(onPage).toHaveBeenCalledWith(2)
  })
})

describe('SearchInput', () => {
  it('debounces typing into a single change, commits on Enter, clears with the X', async () => {
    const onChange = vi.fn()
    render(<SearchInput value="" onChange={onChange} delay={120} placeholder="Search things" />)
    const box = screen.getByRole('searchbox', { name: 'Search things' })
    await userEvent.type(box, 'abc')
    expect(onChange).not.toHaveBeenCalled()
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    expect(onChange).toHaveBeenCalledWith('abc')
    await userEvent.type(box, 'd{Enter}')
    expect(onChange).toHaveBeenLastCalledWith('abcd')
    await userEvent.click(screen.getByRole('button', { name: 'Clear search' }))
    expect(onChange).toHaveBeenLastCalledWith('')
  })
  it('adopts external value changes (e.g. "Clear filters")', () => {
    const { rerender } = render(<SearchInput value="react" onChange={() => {}} />)
    expect(screen.getByRole('searchbox')).toHaveValue('react')
    rerender(<SearchInput value="" onChange={() => {}} />)
    expect(screen.getByRole('searchbox')).toHaveValue('')
  })
})

describe('Combobox / MultiSelect', () => {
  const options = [
    { value: 'a', label: 'Alpha' },
    { value: 'b', label: 'Beta' },
    { value: 'c', label: 'Gamma' },
  ]
  it('single select: filters while typing and selects with the keyboard', async () => {
    function Harness() {
      const [v, setV] = useState('')
      return (
        <Combobox value={v} onChange={setV} options={options} placeholder="Pick one" aria-label="Letter" />
      )
    }
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('combobox', { name: 'Letter' }))
    await user.type(await screen.findByPlaceholderText('Search…'), 'gam')
    expect(screen.queryByRole('option', { name: /Alpha/ })).not.toBeInTheDocument()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('combobox', { name: 'Letter' })).toHaveTextContent('Gamma')
  })
  it('multi select: toggles values and shows removable chips', async () => {
    function Harness() {
      const [v, setV] = useState<string[]>([])
      return (
        <MultiSelect values={v} onChange={setV} options={options} placeholder="Pick" aria-label="Letters" />
      )
    }
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('combobox', { name: 'Letters' }))
    await user.click(await screen.findByRole('option', { name: /Alpha/ }))
    await user.click(screen.getByRole('option', { name: /Beta/ }))
    await user.keyboard('{Escape}')
    const chips = screen.getByRole('list', { name: 'Selected' })
    expect(within(chips).getByText('Alpha')).toBeInTheDocument()
    await user.click(within(chips).getByRole('button', { name: 'Remove Alpha' }))
    expect(
      within(screen.getByRole('list', { name: 'Selected' })).queryByText('Alpha'),
    ).not.toBeInTheDocument()
  })
  it('SimpleSelect maps an explicit "any" item to an empty value', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(
      <SimpleSelect
        value=""
        onValueChange={onChange}
        options={options}
        emptyLabel="Any letter"
        aria-label="Letter"
      />,
    )
    expect(screen.getByRole('combobox', { name: 'Letter' })).toHaveTextContent('Any letter')
    await user.click(screen.getByRole('combobox', { name: 'Letter' }))
    await user.click(await screen.findByRole('option', { name: 'Beta' }))
    expect(onChange).toHaveBeenCalledWith('b')
  })
})

describe('FileDropzone', () => {
  const pdf = (name = 'cv.pdf', size = 1024) =>
    new File([new Uint8Array(size)], name, { type: 'application/pdf' })
  it('accepts a valid file', async () => {
    const onFile = vi.fn()
    const { container } = render(<FileDropzone accept={['.pdf', '.docx']} maxSizeMB={1} onFile={onFile} />)
    await userEvent.upload(container.querySelector('input[type=file]') as HTMLInputElement, pdf())
    expect(onFile).toHaveBeenCalledTimes(1)
  })
  it('rejects the wrong type and oversized files with a clear message', async () => {
    const onFile = vi.fn()
    const { container } = render(<FileDropzone accept={['.pdf']} maxSizeMB={1} onFile={onFile} />)
    const input = container.querySelector('input[type=file]') as HTMLInputElement
    await userEvent.upload(input, new File(['x'], 'notes.txt', { type: 'text/plain' }), {
      applyAccept: false,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('Unsupported file type')
    await userEvent.upload(input, pdf('big.pdf', 2 * 1024 * 1024))
    expect(await screen.findByRole('alert')).toHaveTextContent('too large')
    expect(onFile).not.toHaveBeenCalled()
  })
  it('shows the selected file with upload progress', () => {
    render(<FileDropzone onFile={() => {}} file={pdf('cv.pdf')} progress={0.4} />)
    expect(screen.getByText('cv.pdf')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Uploading cv.pdf' })).toHaveAttribute(
      'aria-valuenow',
      '40',
    )
  })
})

describe('ConfirmDialog', () => {
  it('confirms or cancels, and keeps the dialog open while loading', async () => {
    const onConfirm = vi.fn()
    const onOpenChange = vi.fn()
    const user = userEvent.setup()
    const { rerender } = render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        title="Delete?"
        description="Gone forever"
        confirmLabel="Delete"
        destructive
        onConfirm={onConfirm}
      />,
    )
    expect(screen.getByRole('alertdialog', { name: 'Delete?' })).toHaveAccessibleDescription('Gone forever')
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
    onOpenChange.mockClear()
    rerender(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        title="Delete?"
        confirmLabel="Delete"
        loading
        onConfirm={onConfirm}
      />,
    )
    await user.keyboard('{Escape}')
    expect(onOpenChange).not.toHaveBeenCalled() // can't be dismissed mid-request
  })
})

describe('small components', () => {
  it('PageHeader: breadcrumbs mark the current page, title is the only h1', () => {
    render(
      <MemoryRouter>
        <PageHeader
          title="Jobs"
          description="All jobs"
          breadcrumbs={[{ label: 'Home', to: '/' }, { label: 'Jobs' }]}
          actions={<button>New</button>}
        />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { level: 1, name: 'Jobs' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/')
    expect(screen.getByText('Jobs', { selector: '[aria-current="page"]' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New' })).toBeInTheDocument()
  })
  it('KpiCard renders value, hint, trend and can be a link', () => {
    render(
      <MemoryRouter>
        <KpiCard
          label="Open jobs"
          value={12}
          hint="3 closing soon"
          change={4.2}
          to="/manage/jobs"
          icon={<span />}
        />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link')).toHaveAttribute('href', '/manage/jobs')
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('+4.2%')).toBeInTheDocument()
  })
  it('SkillChip is removable; SkillChipList collapses overflow', async () => {
    const onRemove = vi.fn()
    render(
      <>
        <SkillChip name="Python" onRemove={onRemove} />
        <SkillChipList names={['A', 'B', 'C', 'D']} max={2} />
      </>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Remove Python' }))
    expect(onRemove).toHaveBeenCalled()
    expect(screen.getByText('+2')).toBeInTheDocument()
  })
  it('Timeline renders events in order', () => {
    render(
      <Timeline
        items={[
          { id: '1', title: 'Applied', time: 'Mon' },
          { id: '2', title: 'Screening', description: 'Reviewed by Riley' },
        ]}
      />,
    )
    const items = screen.getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Applied')
    expect(items[1]).toHaveTextContent('Reviewed by Riley')
  })
  it('Stepper marks completed and current steps', () => {
    render(
      <Stepper
        current={1}
        steps={[
          { id: 'a', label: 'Applied' },
          { id: 'b', label: 'Screening' },
          { id: 'c', label: 'Offer' },
        ]}
      />,
    )
    expect(screen.getByText('Screening').closest('li')).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText('(completed)')).toBeInTheDocument()
  })
  it('TextBlock renders paragraphs and bullet lists, never HTML', () => {
    const { container } = render(
      <TextBlock text={'Intro paragraph.\n\n- first\n- second\n\n<script>alert(1)</script>'} />,
    )
    expect(screen.getAllByRole('listitem').map((l) => l.textContent)).toEqual(['first', 'second'])
    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByText('<script>alert(1)</script>')).toBeInTheDocument()
  })
})
