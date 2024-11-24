#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <pthread.h>
#include <stdbool.h>

const int BROADCAST_PORT = 5001;
const int TCP_PORT = 6000;
const int BUFFER_SIZE = 1024;

int main(int argc, char *argv[]) {
    int udp_socket;
    struct sockaddr_in broadcast_addr, master_addr;
    socklen_t addr_len = sizeof(master_addr);
    char buffer[BUFFER_SIZE];

    if ((udp_socket = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        perror("UDP socket creation failed");
    }

    memset(&broadcast_addr, 0, sizeof(broadcast_addr));
    broadcast_addr.sin_family = AF_INET;
    broadcast_addr.sin_port = htons(BROADCAST_PORT);
    broadcast_addr.sin_addr.s_addr = INADDR_ANY;
    if (bind(udp_socket, (struct sockaddr *)&broadcast_addr, sizeof(broadcast_addr)) < 0) {
        perror("UDP socket bind failed");
    }


    int tcp_socket;
    struct sockaddr_in server_addr;

    if ((tcp_socket = socket(AF_INET, SOCK_STREAM, 0)) < 0) {
        perror("TCP socket creation failed");
    }

    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(TCP_PORT);
    server_addr.sin_addr.s_addr = INADDR_ANY;

    if (bind(tcp_socket, (struct sockaddr *)&server_addr, sizeof(server_addr)) < 0) {
        perror("TCP socket bind failed");
    }

    if (listen(tcp_socket, 5) < 0) {
        perror("TCP listen failed");
    }

    printf("Udp port %d\n", BROADCAST_PORT);
    printf("Tcp port %d\n", TCP_PORT);
    fflush(stdout);

    while (1) {
        ssize_t received = recvfrom(udp_socket, buffer, BUFFER_SIZE, 0, (struct sockaddr *)&master_addr, &addr_len);
        if (received < 0) {
            perror("Failed to receive broadcast message");
        }
        buffer[received] = '\0';

        if (strcmp(buffer, "DISCOVER_WORKERS") == 0) {
            printf("Broadcast from %s\n", inet_ntoa(master_addr.sin_addr));

            // send response with tcp port
            snprintf(buffer, BUFFER_SIZE, "%d", TCP_PORT);
            if (sendto(udp_socket, buffer, strlen(buffer), 0, (struct sockaddr *)&master_addr, addr_len) < 0) {
                perror("Failed to send response");
            }
            printf("send broadcast response (port) = %s\n", buffer);
            break;
        }
    }

    while (1) {
        int client_socket;
        struct sockaddr_in client_addr;
        socklen_t client_len = sizeof(client_addr);
        client_socket = accept(tcp_socket, (struct sockaddr *)&client_addr, &client_len);
        if (client_socket < 0) {
            perror("Client connection failed");
            continue;
        }
        ssize_t received = recv(client_socket, buffer, BUFFER_SIZE - 1, 0);
        if (received <= 0) {
            close(client_socket);
            continue;
        }
        buffer[received] = '\0';
        printf("Received message: %s\n", buffer);
        fflush(stdout);
        char message_buffer[BUFFER_SIZE];
        int worker_id;
        if (sscanf(buffer, "ping %d", &worker_id) > 0) {
            snprintf(message_buffer, BUFFER_SIZE, "pong %d", worker_id);
            printf("Sending pong\n");
            fflush(stdout);
        }
        else {
            float left, right;
            int id;
            sscanf(buffer, "%f %f %d", &left, &right, &id);
            
            int step = 100;
            float result = 0;
            while (step) {
                // y = 2x + 3
                float x = left + ((right - left) / 100) * step;
                result += (2 * x + 3) * (right - left) / 100;
                step--;
            }
            snprintf(message_buffer, BUFFER_SIZE, "%f %d", result, id);
            printf("Sending result: %f\n", result);
            fflush(stdout);
        }


        if (send(client_socket, message_buffer, strlen(message_buffer), 0) < 0) {
            perror("Failed to send response");
        }
        close(client_socket);
    }

    close(tcp_socket);
    close(udp_socket);
    return 0;
}
