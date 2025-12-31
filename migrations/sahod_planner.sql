-- Sahod Planner (4.1 to 4.5) - Supabase SQL
-- Targets existing Kaban table: kaban_transactions (has transaction_date already)

create extension if not exists pgcrypto;

-- 4.1 ENVELOPES
create table if not exists public.envelopes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  emoji text default '📦',
  color text default '#6366f1',
  target_amount numeric,
  is_rollover boolean default false,
  cookie_jar numeric default 0,
  sort_order int default 0,
  is_active boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_envelopes_user_id on public.envelopes(user_id);
create index if not exists idx_envelopes_active on public.envelopes(user_id, is_active);

alter table public.envelopes enable row level security;

drop policy if exists "Users can view own envelopes" on public.envelopes;
create policy "Users can view own envelopes"
  on public.envelopes for select
  using (auth.uid() = user_id);

drop policy if exists "Users can create own envelopes" on public.envelopes;
create policy "Users can create own envelopes"
  on public.envelopes for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can update own envelopes" on public.envelopes;
create policy "Users can update own envelopes"
  on public.envelopes for update
  using (auth.uid() = user_id);

drop policy if exists "Users can delete own envelopes" on public.envelopes;
create policy "Users can delete own envelopes"
  on public.envelopes for delete
  using (auth.uid() = user_id);


-- 4.2 PAY CYCLES (template)
create table if not exists public.pay_cycles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  cycle_name text default 'My Salary',
  expected_amount numeric not null,
  frequency text not null,
  pay_day_1 int,
  pay_day_2 int,
  pay_day_of_week int,
  is_active boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),

  constraint valid_frequency check (frequency in ('monthly', 'bimonthly', 'weekly')),
  constraint valid_pay_day_1 check (pay_day_1 is null or pay_day_1 between 1 and 31),
  constraint valid_pay_day_2 check (pay_day_2 is null or pay_day_2 between 1 and 31),
  constraint valid_pay_day_of_week check (pay_day_of_week is null or pay_day_of_week between 1 and 7),
  constraint valid_schedule_by_frequency check (
    (frequency in ('monthly', 'bimonthly') and pay_day_1 is not null and pay_day_of_week is null)
    or
    (frequency = 'weekly' and pay_day_of_week is not null and pay_day_1 is null and pay_day_2 is null)
  )
);

create index if not exists idx_pay_cycles_user_id on public.pay_cycles(user_id);

alter table public.pay_cycles enable row level security;

drop policy if exists "Users can manage own pay cycles" on public.pay_cycles;
create policy "Users can manage own pay cycles"
  on public.pay_cycles for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);


-- 4.3 PAY CYCLE INSTANCES (events)
create table if not exists public.pay_cycle_instances (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  pay_cycle_id uuid not null references public.pay_cycles(id) on delete cascade,

  expected_amount numeric not null,
  actual_amount numeric,

  period_start date not null,
  period_end date not null,
  expected_pay_date date not null,

  is_assumed boolean default true,
  confirmed_at timestamptz,
  auto_confirmed_at timestamptz,

  created_at timestamptz default now(),
  updated_at timestamptz default now(),

  constraint unique_instance unique (pay_cycle_id, period_start)
);

create index if not exists idx_pay_cycle_instances_user on public.pay_cycle_instances(user_id);
create index if not exists idx_pay_cycle_instances_period on public.pay_cycle_instances(user_id, period_start, period_end);
create index if not exists idx_pay_cycle_instances_assumed
  on public.pay_cycle_instances(user_id, is_assumed)
  where is_assumed = true;

alter table public.pay_cycle_instances enable row level security;

drop policy if exists "Users can manage own pay cycle instances" on public.pay_cycle_instances;
create policy "Users can manage own pay cycle instances"
  on public.pay_cycle_instances for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);


-- 4.4 ALLOCATIONS (per period + envelope)
create table if not exists public.allocations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  pay_cycle_instance_id uuid not null references public.pay_cycle_instances(id) on delete cascade,
  envelope_id uuid not null references public.envelopes(id) on delete cascade,

  target_percentage numeric,
  allocated_amount numeric not null,
  cached_spent numeric default 0,
  rollover_amount numeric default 0,

  created_at timestamptz default now(),

  constraint unique_allocation unique (pay_cycle_instance_id, envelope_id)
);

create index if not exists idx_allocations_user_id on public.allocations(user_id);
create index if not exists idx_allocations_envelope on public.allocations(envelope_id);
create index if not exists idx_allocations_instance on public.allocations(pay_cycle_instance_id);

alter table public.allocations enable row level security;

drop policy if exists "Users can manage own allocations" on public.allocations;
create policy "Users can manage own allocations"
  on public.allocations for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);


-- 4.5 KABAN TRANSACTIONS: add envelope_id + indexes
alter table public.kaban_transactions
  add column if not exists envelope_id uuid references public.envelopes(id);

create index if not exists idx_kaban_transactions_envelope on public.kaban_transactions(envelope_id);
create index if not exists idx_kaban_transactions_user_envelope_date
  on public.kaban_transactions(user_id, envelope_id, transaction_date);


-- Trigger: keep allocations.cached_spent in sync (per period)
create or replace function public.recalculate_allocation_for_date(
  p_user_id uuid,
  p_envelope_id uuid,
  p_tx_date date
) returns void as $$
declare
  v_instance_id uuid;
  v_start date;
  v_end date;
begin
  select id, period_start, period_end
    into v_instance_id, v_start, v_end
  from public.pay_cycle_instances
  where user_id = p_user_id
    and p_tx_date between period_start and period_end
  order by period_start desc
  limit 1;

  if v_instance_id is null then
    return;
  end if;

  update public.allocations
  set cached_spent = (
    select coalesce(sum(amount), 0)
    from public.kaban_transactions
    where user_id = p_user_id
      and envelope_id = p_envelope_id
      and transaction_type = 'expense'
      and transaction_date between v_start and v_end
  )
  where user_id = p_user_id
    and pay_cycle_instance_id = v_instance_id
    and envelope_id = p_envelope_id;
end;
$$ language plpgsql;

create or replace function public.trg_handle_kaban_transaction_change()
returns trigger as $$
begin
  -- OLD context (DELETE/UPDATE)
  if (TG_OP = 'DELETE' or TG_OP = 'UPDATE') and OLD.envelope_id is not null then
    perform public.recalculate_allocation_for_date(OLD.user_id, OLD.envelope_id, OLD.transaction_date);
  end if;

  -- NEW context (INSERT/UPDATE)
  if (TG_OP = 'INSERT' or TG_OP = 'UPDATE') and NEW.envelope_id is not null then
    perform public.recalculate_allocation_for_date(NEW.user_id, NEW.envelope_id, NEW.transaction_date);
  end if;

  return null;
end;
$$ language plpgsql;

drop trigger if exists trg_update_allocation_spent on public.kaban_transactions;

create trigger trg_update_allocation_spent
after insert or update or delete on public.kaban_transactions
for each row
execute function public.trg_handle_kaban_transaction_change();