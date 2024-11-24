#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/epoll.h>
#include <netinet/tcp.h>
#include <stdbool.h>

const int BROADCAST_PORT = 5001;
const int BUFFER_SIZE = 1024;
const int TIMEOUT_SECONDS = 2;
const int MAX_WORKERS = 10;

void set_tcp_keepalive(int socket) {
    int so_keepalive = 1;
    if (setsockopt(socket, SOL_SOCKET, SO_KEEPALIVE, &so_keepalive, sizeof(so_keepalive)) < 0) {
        perror("Failed to set SO_KEEPALIVE");
        return;
    }

    int keepidle = 1;
    if (setsockopt(socket, IPPROTO_TCP, TCP_KEEPIDLE, &keepidle, sizeof(keepidle)) < 0) {
        perror("Failed to set TCP_KEEPIDLE");
    }

    int keepintvl = 1;
    if (setsockopt(socket, IPPROTO_TCP, TCP_KEEPINTVL, &keepintvl, sizeof(keepintvl)) < 0) {
        perror("Failed to set TCP_KEEPINTVL");
    }

    int keepcnt = 1;
    if (setsockopt(socket, IPPROTO_TCP, TCP_KEEPCNT, &keepcnt, sizeof(keepcnt)) < 0) {
        perror("Failed to set TCP_KEEPCNT");
    }
}


struct Task {
    float left;
    float right;
    bool computed;
};

int main() {
    int udp_socket, tcp_socket;
    struct sockaddr_in broadcast_addr, worker_addr;
    socklen_t addr_len = sizeof(worker_addr);
    char buffer[BUFFER_SIZE];

    if ((udp_socket = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        perror("UDP socket creation failed");
    }

    int broadcast_enable = 1;
    if (setsockopt(udp_socket, SOL_SOCKET, SO_BROADCAST, &broadcast_enable, sizeof(broadcast_enable)) < 0) {
        perror("Failed to enable broadcast option");
    }

    struct timeval timeout;
    timeout.tv_sec = TIMEOUT_SECONDS;
    timeout.tv_usec = 0;
    if (setsockopt(udp_socket, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) < 0) {
        perror("Failed to set socket timeout");
    }
    memset(&broadcast_addr, 0, sizeof(broadcast_addr));
    broadcast_addr.sin_family = AF_INET;
    broadcast_addr.sin_port = htons(BROADCAST_PORT);
    broadcast_addr.sin_addr.s_addr = INADDR_BROADCAST;

    // broadcat
    const char *message = "DISCOVER_WORKERS";
    if (sendto(udp_socket, message, strlen(message), 0, (struct sockaddr *)&broadcast_addr, sizeof(broadcast_addr)) < 0) {
        perror("Broadcast message send failed");
    }
    printf("Broadcast sent\n");


    struct sockaddr_in worker_list[MAX_WORKERS];
    int worker_ports[MAX_WORKERS];
    int worker_count = 0;

    while (1) {
        ssize_t received = recvfrom(udp_socket, buffer, BUFFER_SIZE, 0, (struct sockaddr *)&worker_addr, &addr_len);
        if (received < 0) {
            printf("Broadcast timeout passed\n");
            break;
        }
        buffer[received] = '\0';
        worker_list[worker_count] = worker_addr;
        worker_ports[worker_count] = atoi(buffer);
        ++worker_count;
        printf("worker found: %s: %s\n", inet_ntoa(worker_addr.sin_addr), buffer);
    }
    // for tests, to set packet loss
    sleep(10);

    // Split the task
    float left = 0, right = 10;
    struct Task tasks[worker_count];
    for (int i = 0; i < worker_count; ++i) {
        tasks[i].left = left + ((left + right) / (float)worker_count) * (float)i;
        tasks[i].right = left + ((left + right) / (float)worker_count) * (float)(i + 1);
        tasks[i].computed = false;
    }
    
    bool is_worker_alive[worker_count];
    for (int i = 0; i < worker_count; ++i) {
        is_worker_alive[i] = true;
    }
    int computed_tasks = 0;
    float result = 0;

    while (computed_tasks < worker_count) {

        int epoll_fd = epoll_create1(0);
        if (epoll_fd < 0) {
            perror("Failed to create epoll instance");
        }

        struct epoll_event event, events[worker_count];
        int worker_sockets[worker_count];

        int current_task = 0;
        bool found_alive = false;

        int worker_task[worker_count];

        for (int i = 0; i < worker_count; i++) {
            worker_task[i] = -1;
            if (is_worker_alive[i]) {
                found_alive = true;
            }
            if ((tcp_socket = socket(AF_INET, SOCK_STREAM, 0)) < 0) {
                perror("TCP socket creation failed");
            }

            struct sockaddr_in worker_tcp_addr = worker_list[i];
            worker_tcp_addr.sin_port = htons(worker_ports[i]);
            struct timeval timeout;      
            timeout.tv_sec = 1;
            timeout.tv_usec = 0;
            
            if (setsockopt (tcp_socket, SOL_SOCKET, SO_RCVTIMEO, &timeout,
                        sizeof timeout) < 0)
                perror("setsockopt failed\n");

            if (setsockopt (tcp_socket, SOL_SOCKET, SO_SNDTIMEO, &timeout,
                        sizeof timeout) < 0)
                perror("setsockopt failed\n");

            if (connect(tcp_socket, (struct sockaddr *)&worker_tcp_addr, sizeof(worker_tcp_addr)) < 0) {
                perror("Failed to connect to worker");
                is_worker_alive[i] = false;
                close(tcp_socket);
                continue;
            }

            set_tcp_keepalive(tcp_socket);

            // Send message
            char message_buffer[BUFFER_SIZE];
            if (is_worker_alive[i]) {
                for (;current_task < worker_count; ++current_task) {
                    if (!tasks[current_task].computed) {
                        break;
                    }
                }
                if (current_task == worker_count) {
                    close(tcp_socket);
                    continue;
                }
                worker_task[i] = current_task;
                snprintf(message_buffer, BUFFER_SIZE, "%f %f %d", tasks[current_task].left, tasks[current_task].right, current_task);
                ++current_task;
            }
            else {
                snprintf(message_buffer, BUFFER_SIZE, "ping %d", i);
            }
            if (send(tcp_socket, message_buffer, strlen(message_buffer), 0) < 0) {
                perror("Failed to send message");
            } else {
                printf("Sent message to worker at %s:%d\n", inet_ntoa(worker_tcp_addr.sin_addr), worker_ports[i]);
            }

            event.events = EPOLLIN;
            event.data.fd = tcp_socket;
            if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, tcp_socket, &event) < 0) {
                perror("Failed to add socket to epoll");
                close(tcp_socket);
                continue;
            }

            worker_sockets[i] = tcp_socket;
        }
        if (!found_alive) {
            perror("No available workers");
            break;
        }

        fflush(stdout);
        int active_fds = 0;
        while ((active_fds = epoll_wait(epoll_fd, events, MAX_WORKERS, TIMEOUT_SECONDS * 1000)) > 0) {
            for (int i = 0; i < active_fds; i++) {
                int worker_fd = events[i].data.fd;

                ssize_t received = recv(worker_fd, buffer, BUFFER_SIZE - 1, 0);
                if (received > 0) {
                    buffer[received] = '\0';
                    printf("Received response from worker: %s\n", buffer);
                    fflush(stdout);
                    int worker_id;
                    if (sscanf(buffer, "pong %d", &worker_id) > 0) {
                        is_worker_alive[worker_id] = true;
                    }
                    else {
                        float task_result;
                        int id;
                        sscanf(buffer, "%f %d", &task_result, &id);
                        if (tasks[id].computed) {
                            continue;
                        }
                        result += task_result;
                        tasks[id].computed = true;
                        ++computed_tasks;
                    }
                } else {
                    close(worker_fd);
                }
            }
        }

        for (int i = 0; i < worker_count; ++i) {
            if (worker_task[i] != -1 && tasks[worker_task[i]].computed == false) {
                is_worker_alive[i] = false;
            }
        }

        if (active_fds == 0) {
            printf("Epoll timeout");
        }

        for (int i = 0; i < worker_count; i++) {
            close(worker_sockets[i]);
        }
        close(epoll_fd);
    }

    printf("Finished, the result is %f.\n", result);

    close(udp_socket);
    return 0;
}
