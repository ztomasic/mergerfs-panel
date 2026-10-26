# Frequently asked questions

## Is mergerfs the same as LVM or RAID?

No. mergerfs is a *union filesystem*. Each branch is an ordinary mounted filesystem,
and the pool is a directory that merges them by name. Files are stored whole on one
branch. LVM, btrfs multi-device, ZFS, and mdadm work at the block level and present a
single virtual device; a file can span disks, and member disks are no longer visible
as separate filesystems.

## Why do the member disks still appear in my file manager?

Because they are still mounted filesystems. mergerfs needs them mounted to use them,
and keeping them visible is deliberate: each disk remains independently readable if
you remove it, there is no on-disk metadata to reconstruct, and a failed disk only
affects its own files. See
[ARCHITECTURE.md](ARCHITECTURE.md#why-a-pool-is-not-a-device) for why the pool itself
cannot appear there.

## Can I hide the member disks from the file manager?

You can mark them ignored for UDisks2-based interfaces with a udev rule
(`ENV{UDISKS_IGNORE}="1"`). That is cosmetic: it does not change capacity, and this
app would still list the disks because it reads UDisks2 directly. It is not
recommended unless the duplicate entries bother you more than the lost visibility.

## Does the pool show the combined free space?

Yes, as an aggregate. `statfs` on the pool sums the branches: an 8 GB and a 21 GB
branch report about 29 GB total. `minfreespace` reduces what is usable for new
writes, and a branch can be excluded from create policies with `RO`/`NC`.

## Can a single file be larger than the largest disk?

No. Files are never split across branches. A file must fit on one branch. This is the
main practical difference from LVM/RAID-style pooling.

## What happens if one disk fails?

The pool keeps serving the files on the surviving branches. Files that lived only on
the failed disk are missing until it returns; nothing tries to rebuild them. mergerfs
is not RAID and has no parity.

## Can I add or remove a disk while the pool is mounted?

Yes. The app writes to the `user.mergerfs.branches` xattr, and mergerfs applies the
change immediately without unmounting. Open files keep working. Removing a branch
leaves its data on the disk but makes it disappear from the merged directory.

## Where do new files go?

According to the create policy. The app's default is `mfs` (most free space). Use
`epmfs` if you want new files to follow existing directories, keeping a folder's
contents on the same disk. `minfreespace` stops a disk from being filled completely.

## Can I mix filesystems and disk sizes?

Yes. mergerfs supports any mounted filesystem and any size; branches do not need to
match. Fat32/vfat lacks POSIX permissions and xattrs, which some applications need,
but it works for plain files.

## Can the pool be mounted at boot?

Yes, through `/etc/fstab` or a systemd mount unit, both of which run as root. Example:

```fstab
/run/media/you/disk1:/run/media/you/disk2  /srv/media  mergerfs  defaults,nofail,allow_other,category.create=mfs,minfreespace=4G  0 0
```

`nofail` lets the system boot when a branch is missing. Make sure the branch
filesystems are mounted first (`x-systemd.requires=` for fstab entries).

## Can other users and services read the pool?

Only if the mount was created with `allow_other` (and, for a user-run mount, with
`user_allow_other` in `/etc/fuse.conf`). A root-run mount with `allow_other` is the
usual setup for a web server or media server.

## Why is the pool at `~/mergerfs` and not `/media`?

Pools need a mount point; a user-owned directory under your home can be mounted by an
unprivileged FUSE process. `/media` and `/mnt` are root-owned system directories.
For a service or a multi-user setup, mount at `/srv/media` (or similar) as root.

## Can I rename a pool?

The app has no rename action. A pool's name is its mount point. To rename, unmount the
pool, rename or create the mount point, mount again, and update the config file entry
(or create a new pool and remove the old one).

## Can I have several pools?

Yes. Pools are independent mounts, and a disk can be a branch of more than one pool,
although that is rarely useful.

## Does the app store my files or copy data?

No. It only changes mount options and the branch list. Files are written by mergerfs
straight to the branches.

## Does it work with containers?

Bind-mount the pool into the container. If the container runs with a different user
namespace, the host FUSE mount needs `allow_other`, and the container user must be
able to traverse the mount point. A root-mounted pool at a stable path is the least
surprising setup.

## Is there a Windows or macOS version?

No. The app targets Linux desktop stacks (GTK4, UDisks2, FUSE) and mergerfs itself is
Linux-only.
