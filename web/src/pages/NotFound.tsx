import { Compass } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Page } from '../components/AppShell'
import { Empty, Panel, SectionHeader } from '../components/primitives'

export default function NotFound() {
  return (
    <Page className="space-y-12">
      <SectionHeader index="—" title="Not found" description="That route does not exist in this application." />
      <Panel>
        <Empty
          icon={Compass}
          title="Nothing at this address"
          detail="The page may have been moved, or the link may be wrong."
          action={
            <Link
              to="/"
              className="mt-2 inline-flex items-center border-2 border-ink bg-ink px-4 py-2.5 text-meta font-bold uppercase tracking-wide text-paper transition-colors duration-150 ease-linear hover:border-accent hover:bg-accent"
            >
              Back to overview
            </Link>
          }
        />
      </Panel>
    </Page>
  )
}
